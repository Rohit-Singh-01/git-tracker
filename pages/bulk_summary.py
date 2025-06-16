


import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import date
from dateutil import parser

# --- CONFIG ---
GITLAB_TOKEN = st.secrets["gitlab"]["token"]
BASE_URL = st.secrets["gitlab"]["base_url"]

# --- SESSION STATE ---
if "usernames" not in st.session_state:
    st.session_state.usernames = []
if "bulk_data" not in st.session_state:
    st.session_state.bulk_data = {}
if "mode" not in st.session_state:
    st.session_state.mode = None


# --- RESET FUNCTION ---
def reset():
    st.session_state.usernames = []
    st.session_state.bulk_data = {}
    st.session_state.mode = None
    st.rerun()


# --- API FUNCTIONS ---
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
def count_items_by_date(items, field, start, end):
    count = 0
    for item in items:
        try:
            if field in item and item[field]:
                d = parser.parse(item[field]).date()
                if start <= d <= end:
                    count += 1
        except:
            continue
    return count


# --- GATHER DATA ---
async def gather_user_data(username):
    async with aiohttp.ClientSession() as session:
        user = await fetch_user(session, username)
        if not user:
            raise ValueError("User not found")

        user_id = user["id"]
        user_email = user.get("public_email") or user.get("email", "")

        personal_projects = await fetch_user_projects(session, user_id)
        contributed_projects = await fetch_contributed_projects(session, user_id)

        contrib_data = {}

        for proj in contributed_projects:
            pid = proj["id"]
            pname = proj["name_with_namespace"]
            contrib_data[pname] = {"commits": [], "mrs": [], "issues": []}

            try:
                commits = await fetch_commits(session, pid, user_email)
                contrib_data[pname]["commits"] = commits
            except:
                pass

            try:
                mrs = await fetch_merge_requests(session, user_id, pid)
                for mr in mrs:
                    try:
                        comments = await fetch_mr_comments(session, pid, mr["iid"])
                        mr["comment_count"] = len(comments)
                    except:
                        mr["comment_count"] = 0
                contrib_data[pname]["mrs"] = mrs
            except:
                pass

            try:
                issues = await fetch_issues(session, user_id, pid)
                for issue in issues:
                    try:
                        comments = await fetch_issue_comments(
                            session, pid, issue["iid"]
                        )
                        issue["comment_count"] = len(comments)
                    except:
                        issue["comment_count"] = 0
                contrib_data[pname]["issues"] = issues
            except:
                pass

        return user, personal_projects, contributed_projects, contrib_data


# --- UI ---
st.title("📦 GitLab Bulk Tracker")
st.button("🔄 Reset All", on_click=reset)

st.subheader("👥 Enter Usernames")
c1, c2 = st.columns(2)

with c1:
    csv = st.file_uploader("Upload CSV with 'username' column", type="csv")
    if csv:
        try:
            df = pd.read_csv(csv)
            usernames = df["username"].dropna().astype(str).str.strip().tolist()
            st.session_state.usernames = usernames
            st.session_state.mode = "csv"
            st.success(f"Loaded {len(usernames)} usernames")
        except:
            st.error("Error reading CSV")

with c2:
    raw = st.text_area("Or enter comma-separated usernames")
    if raw:
        usernames = [u.strip() for u in raw.split(",") if u.strip()]
        st.session_state.usernames = usernames
        st.session_state.mode = "manual"
        st.success(f"Added {len(usernames)} usernames")

# --- DATE FILTER ---
st.subheader("📅 Filter by Date Range")
col_start, col_end = st.columns(2)
start_date = col_start.date_input("Start Date", value=date(2020, 1, 1))
end_date = col_end.date_input("End Date", value=date.today())
if start_date > end_date:
    st.warning("Start date cannot be after end date. Resetting.")
    start_date, end_date = date(2020, 1, 1), date.today()

# --- PROCESS USERS (PRINT WHATEVER FETCHED) ---
usernames = st.session_state.usernames


async def process_users():
    for username in usernames:
        status = st.empty()
        user_container = st.container()

        if username in st.session_state.bulk_data:
            status.success(f"✅ {username} (cached)")
            continue

        try:
            status.info(f"⏳ Fetching {username}...")
            user, personal, contrib, contrib_data = await gather_user_data(username)
            st.session_state.bulk_data[username] = (
                user,
                personal,
                contrib,
                contrib_data,
            )
            status.success(f"✅ {username} fetched")
        except Exception as e:
            status.error(f"❌ {username}: {e}")
            continue

        with user_container:
            st.subheader(f"👤 {user['name']} (@{user['username']})")

            st.write("📁 **Projects Summary**")
            col1, col2, col3 = st.columns(3)
            col1.metric("Personal Projects", len(personal))
            col2.metric("Contributed Projects", len(contrib))
            col3.metric("Total", len(personal) + len(contrib))

            tc, tm, ti = 0, 0, 0
            ic, mc = 0, 0

            for pdata in contrib_data.values():
                tc += count_items_by_date(
                    pdata["commits"], "created_at", start_date, end_date
                )
                tm += count_items_by_date(
                    pdata["mrs"], "created_at", start_date, end_date
                )
                ti += count_items_by_date(
                    pdata["issues"], "created_at", start_date, end_date
                )
                ic += sum(i.get("comment_count", 0) for i in pdata["issues"])
                mc += sum(m.get("comment_count", 0) for m in pdata["mrs"])

            st.write(f"📈 **Contributions ({start_date} → {end_date})**")
            c1, c2, c3 = st.columns(3)
            c1.metric("📝 Commits", tc)
            c2.metric("📦 Merge Requests", tm)
            c3.metric("🐞 Issues", ti)

            st.metric("💬 MR Comments", mc)
            st.metric("💬 Issue Comments", ic)
            st.metric("🏆 Total Contributions", tc + tm + ti)

            with st.expander("🔍 View Project Details"):
                for project_name, pdata in contrib_data.items():
                    pc = count_items_by_date(
                        pdata["commits"], "created_at", start_date, end_date
                    )
                    pm = count_items_by_date(
                        pdata["mrs"], "created_at", start_date, end_date
                    )
                    pi = count_items_by_date(
                        pdata["issues"], "created_at", start_date, end_date
                    )
                    pmc = sum(m.get("comment_count", 0) for m in pdata["mrs"])
                    pic = sum(i.get("comment_count", 0) for i in pdata["issues"])

                    if pc or pm or pi:
                        st.write(f"**{project_name}**")
                        st.write(f"- Commits: {pc}")
                        st.write(f"- Merge Requests: {pm} (💬 {pmc} comments)")
                        st.write(f"- Issues: {pi} (💬 {pic} comments)")
                        st.write("---")


if usernames:
    asyncio.run(process_users())
