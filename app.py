



import streamlit as st
import asyncio
import aiohttp
from datetime import date
from dateutil import parser

# --- CONFIG ---
GITLAB_TOKEN = st.secrets["gitlab"]["token"]
BASE_URL = st.secrets["gitlab"]["base_url"]

# --- SESSION STATE INIT ---
if "fetched_username" not in st.session_state:
    st.session_state.fetched_username = None
if "fetched_user_data" not in st.session_state:
    st.session_state.fetched_user_data = None


# --- API FETCH FUNCTIONS ---
async def fetch_json(session, url, params=None):
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    async with session.get(url, headers=headers, params=params) as response:
        response.raise_for_status()
        return await response.json()


async def fetch_user(session, username):
    users = await fetch_json(
        session, f"{BASE_URL}/users", params={"username": username}
    )
    return users[0] if users else None


async def fetch_user_projects(session, user_id):
    return await fetch_json(session, f"{BASE_URL}/users/{user_id}/projects")


async def fetch_contributed_projects(session, user_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/users/{user_id}/contributed_projects",
        params={"per_page": 100},
    )


async def fetch_commits(session, project_id, user_email):
    return await fetch_json(
        session,
        f"{BASE_URL}/projects/{project_id}/repository/commits",
        params={"author_email": user_email},
    )


async def fetch_merge_requests(session, user_id, project_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/projects/{project_id}/merge_requests",
        params={"author_id": user_id},
    )


async def fetch_issues(session, user_id, project_id):
    return await fetch_json(
        session,
        f"{BASE_URL}/projects/{project_id}/issues",
        params={"author_id": user_id},
    )


async def fetch_issue_comments(session, project_id, issue_iid):
    return await fetch_json(
        session, f"{BASE_URL}/projects/{project_id}/issues/{issue_iid}/notes"
    )


async def fetch_mr_comments(session, project_id, mr_iid):
    return await fetch_json(
        session, f"{BASE_URL}/projects/{project_id}/merge_requests/{mr_iid}/notes"
    )


# --- COUNT HELPER ---
def count_items_by_date(items, date_field, start_date, end_date):
    count = 0
    for item in items:
        try:
            if date_field in item and item[date_field]:
                item_date = parser.parse(item[date_field]).date()
                if start_date <= item_date <= end_date:
                    count += 1
        except Exception:
            continue
    return count


# --- MAIN GATHER FUNCTION ---
async def gather_data(username):
    async with aiohttp.ClientSession() as session:
        user = await fetch_user(session, username)
        if not user:
            raise ValueError("User not found.")

        user_id = user["id"]
        user_email = user.get("public_email") or user.get("email", "")

        personal_projects = await fetch_user_projects(session, user_id)
        contributed_projects = await fetch_contributed_projects(session, user_id)

        contrib_data = {}

        for project in contributed_projects:
            project_id = project["id"]
            name = project["name_with_namespace"]
            contrib_data[name] = {"commits": [], "mrs": [], "issues": []}

            try:
                commits = await fetch_commits(session, project_id, user_email)
                contrib_data[name]["commits"] = commits
            except:
                pass

            try:
                mrs = await fetch_merge_requests(session, user_id, project_id)
                for mr in mrs:
                    try:
                        comments = await fetch_mr_comments(
                            session, project_id, mr["iid"]
                        )
                        mr["comment_count"] = len(comments)
                    except:
                        mr["comment_count"] = 0
                contrib_data[name]["mrs"] = mrs
            except:
                pass

            try:
                issues = await fetch_issues(session, user_id, project_id)
                for issue in issues:
                    try:
                        comments = await fetch_issue_comments(
                            session, project_id, issue["iid"]
                        )
                        issue["comment_count"] = len(comments)
                    except:
                        issue["comment_count"] = 0
                contrib_data[name]["issues"] = issues
            except:
                pass

        return user, personal_projects, contributed_projects, contrib_data


# --- STREAMLIT UI ---
st.title("📊 GitLab Personal + Contribution Tracker")

# Reset Button
if st.button("🔄 Reset Data"):
    st.session_state.fetched_user_data = None
    st.session_state.fetched_username = None
    st.rerun()

# Username Input
username = st.text_input("Enter GitLab Username")

# Fetch data only if username is entered or previously stored
if username and username != st.session_state.fetched_username:
    with st.spinner("Fetching user data..."):
        try:
            result = asyncio.run(gather_data(username))
            st.session_state.fetched_user_data = result
            st.session_state.fetched_username = username
        except Exception as e:
            st.error(f"❌ {str(e)}")
            st.info(
                "Make sure your GitLab token has correct access and base_url is valid."
            )

# Show data if stored in session
if st.session_state.fetched_user_data:
    user, personal_projects, contributed_projects, contrib_data = (
        st.session_state.fetched_user_data
    )

    st.subheader(f"👤 {user['name']} (@{user['username']})")

    st.subheader("📁 Projects Summary")
    col1, col2, col3 = st.columns(3)
    col1.metric("Personal Projects", len(personal_projects))
    col2.metric("Contributed Projects", len(contributed_projects))
    col3.metric("Total", len(personal_projects) + len(contributed_projects))

    default_start = date(2020, 1, 1)
    default_end = date.today()

    st.subheader("📅 Filter by Date Range")
    col_start, col_end = st.columns(2)
    start_date = col_start.date_input("Start Date", value=default_start)
    end_date = col_end.date_input("End Date", value=default_end)

    if start_date > end_date:
        st.warning("Start date cannot be after end date. Resetting to default range.")
        start_date, end_date = default_start, default_end

    total_commits = total_mrs = total_issues = 0
    total_issue_comments = total_mr_comments = 0

    for pdata in contrib_data.values():
        total_commits += count_items_by_date(
            pdata.get("commits", []), "created_at", start_date, end_date
        )
        total_mrs += count_items_by_date(
            pdata.get("mrs", []), "created_at", start_date, end_date
        )
        total_issues += count_items_by_date(
            pdata.get("issues", []), "created_at", start_date, end_date
        )

        total_issue_comments += sum(
            i.get("comment_count", 0) for i in pdata.get("issues", [])
        )
        total_mr_comments += sum(
            m.get("comment_count", 0) for m in pdata.get("mrs", [])
        )

    st.subheader(f"📈 Contributions ({start_date} → {end_date})")
    c1, c2, c3 = st.columns(3)
    c1.metric("📝 Commits", total_commits)
    c2.metric("📦 Merge Requests", total_mrs)
    c3.metric("🐞 Issues", total_issues)

    st.metric("💬 MR Comments", total_mr_comments)
    st.metric("💬 Issue Comments", total_issue_comments)
    st.metric("🏆 Total Contributions", total_commits + total_mrs + total_issues)

    if contrib_data:
        with st.expander("🔍 View Project Details"):
            for project_name, pdata in contrib_data.items():
                sc = count_items_by_date(
                    pdata.get("commits", []), "created_at", start_date, end_date
                )
                sm = count_items_by_date(
                    pdata.get("mrs", []), "created_at", start_date, end_date
                )
                si = count_items_by_date(
                    pdata.get("issues", []), "created_at", start_date, end_date
                )

                issue_comments = sum(
                    i.get("comment_count", 0) for i in pdata.get("issues", [])
                )
                mr_comments = sum(
                    m.get("comment_count", 0) for m in pdata.get("mrs", [])
                )

                if sc or sm or si:
                    st.markdown(f"**{project_name}**")
                    st.write(f"- Commits: {sc}")
                    st.write(f"- Merge Requests: {sm} (💬 {mr_comments} comments)")
                    st.write(f"- Issues: {si} (💬 {issue_comments} comments)")
                    st.write("---")
