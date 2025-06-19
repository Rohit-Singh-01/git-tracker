import streamlit as st
import asyncio
import aiohttp
import pandas as pd
import json
from datetime import date
from dateutil import parser

# --- CONFIG ---
GITLAB_TOKEN = st.secrets["gitlab"]["token"]
BASE_URL = st.secrets["gitlab"]["base_url"]

# --- SESSION STATE INIT ---
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
@st.cache_data(ttl=None, show_spinner=False)
def fetch_json_cached(url, params_str=None):
    import requests
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    params = json.loads(params_str) if params_str else None
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


async def fetch_json(session, url, params=None):
    """Async wrapper that uses the cached sync function"""
    params_str = json.dumps(params) if params else None
    return await asyncio.get_event_loop().run_in_executor(
        None, fetch_json_cached, url, params_str
    )


async def fetch_user(session, username):
    url = f"{BASE_URL}/users"
    params = {"username": username}
    data = await fetch_json(session, url, params)
    return data[0] if data else None


async def fetch_user_projects(session, user_id):
    try:
        return await fetch_json(session, f"{BASE_URL}/users/{user_id}/projects")
    except Exception as e:
        print(f"Error fetching user projects: {e}")
        return []


async def fetch_contributed_projects(session, user_id):
    try:
        return await fetch_json(
            session,
            f"{BASE_URL}/users/{user_id}/contributed_projects",
            params={"per_page": 100},
        )
    except Exception as e:
        print(f"Error fetching contributed projects: {e}")
        return []


async def fetch_commits(session, project_id, user_id, username):
    """Fetch only commits authored by the specific user."""
    user_commits = []

    # Strategy 1: Use username
    try:
        commits = await fetch_json(
            session,
            f"{BASE_URL}/projects/{project_id}/repository/commits",
            params={"author": username, "per_page": 100},
        )
        user_commits.extend(commits)
    except:
        pass

    # Strategy 2: Use email
    try:
        user_info = await fetch_json(session, f"{BASE_URL}/users/{user_id}")
        emails = [user_info.get("email"), user_info.get("public_email")]
        for email in set(emails):
            if email:
                try:
                    commits = await fetch_json(
                        session,
                        f"{BASE_URL}/projects/{project_id}/repository/commits",
                        params={"author_email": email, "per_page": 100},
                    )
                    user_commits.extend(commits)
                except:
                    continue
    except:
        pass

    # Strategy 3: Fallback - Get all recent commits and filter manually
    if not user_commits:
        try:
            all_commits = await fetch_json(
                session,
                f"{BASE_URL}/projects/{project_id}/repository/commits",
                params={"per_page": 100},
            )
            user_info = await fetch_json(session, f"{BASE_URL}/users/{user_id}")
            user_name = user_info.get('name', '').lower()
            user_username = user_info.get('username', '').lower()
            user_emails = [user_info.get('email'), user_info.get('public_email')]
            user_emails = [e.lower() for e in user_emails if e]

            for commit in all_commits:
                author_name = commit.get('author_name', '').lower()
                author_email = commit.get('author_email', '').lower()
                committer_name = commit.get('committer_name', '').lower()
                committer_email = commit.get('committer_email', '').lower()

                name_match = (
                    user_name in author_name or
                    user_username in author_name or
                    user_name in committer_name or
                    user_username in committer_name
                )
                email_match = any(e in author_email or e in committer_email for e in user_emails)

                if name_match or email_match:
                    user_commits.append(commit)
        except:
            pass

    seen_ids = set()
    unique_commits = []
    for commit in user_commits:
        if commit['id'] not in seen_ids:
            seen_ids.add(commit['id'])
            unique_commits.append(commit)
    return unique_commits


async def fetch_merge_requests(session, user_id, project_id):
    try:
        return await fetch_json(
            session,
            f"{BASE_URL}/projects/{project_id}/merge_requests",
            params={"author_id": user_id, "per_page": 100},
        )
    except Exception as e:
        print(f"Error fetching merge requests: {e}")
        return []


async def fetch_issues(session, user_id, project_id):
    try:
        return await fetch_json(
            session,
            f"{BASE_URL}/projects/{project_id}/issues",
            params={"author_id": user_id, "per_page": 100},
        )
    except Exception as e:
        print(f"Error fetching issues: {e}")
        return []


async def fetch_issue_comments(session, project_id, issue_iid, user_id):
    """Fetch only text comments made by the specific user on an issue"""
    try:
        all_comments = await fetch_json(
            session, f"{BASE_URL}/projects/{project_id}/issues/{issue_iid}/notes"
        )
        # Filter comments by the specific user and exclude system notes
        user_comments = [
            comment for comment in all_comments
            if comment.get("author", {}).get("id") == user_id and not comment.get("system", False)
        ]
        return user_comments
    except Exception as e:
        print(f"Error fetching issue comments: {e}")
        return []


async def fetch_mr_comments(session, project_id, mr_iid, user_id):
    """Fetch only text comments made by the specific user on a merge request"""
    try:
        all_comments = await fetch_json(
            session, f"{BASE_URL}/projects/{project_id}/merge_requests/{mr_iid}/notes"
        )
        # Filter comments by the specific user and exclude system notes
        user_comments = [
            comment for comment in all_comments
            if comment.get("author", {}).get("id") == user_id and not comment.get("system", False)
        ]
        return user_comments
    except Exception as e:
        print(f"Error fetching MR comments: {e}")
        return []


# --- COUNT HELPER ---
@st.cache_data(ttl=None, show_spinner=False)
def count_items_by_date_cached(items, field, start, end):
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


def count_items_by_date(items, field, start_date, end_date):
    """Non-cached version for direct use"""
    return count_items_by_date_cached(items, field, start_date, end_date)


# --- GATHER DATA ---
@st.cache_data(ttl=None, show_spinner=False)
def gather_user_data_cached(username):
    """Cached wrapper for gather_user_data"""
    return asyncio.run(gather_user_data(username))


async def gather_user_data(username):
    async with aiohttp.ClientSession() as session:
        user = await fetch_user(session, username)
        if not user:
            raise ValueError("User not found")
        user_id = user["id"]
        personal_projects = await fetch_user_projects(session, user_id)
        contributed_projects = await fetch_contributed_projects(session, user_id)
        contrib_data = {}

        for proj in contributed_projects + personal_projects:
            pid = proj["id"]
            pname = proj["name_with_namespace"]
            contrib_data[pname] = {"commits": [], "mrs": [], "issues": []}

            try:
                commits = await fetch_commits(session, pid, user_id, username)
                contrib_data[pname]["commits"] = commits
            except Exception as e:
                print(f"Error fetching commits for {pname}: {e}")

            try:
                mrs = await fetch_merge_requests(session, user_id, pid)
                for mr in mrs:
                    try:
                        comments = await fetch_mr_comments(session, pid, mr["iid"], user_id)
                        mr["user_comment_count"] = len(comments)
                    except:
                        mr["user_comment_count"] = 0
                contrib_data[pname]["mrs"] = mrs
            except Exception as e:
                print(f"Error fetching MRs for {pname}: {e}")

            try:
                issues = await fetch_issues(session, user_id, pid)
                for issue in issues:
                    try:
                        comments = await fetch_issue_comments(session, pid, issue["iid"], user_id)
                        issue["user_comment_count"] = len(comments)
                    except:
                        issue["user_comment_count"] = 0
                contrib_data[pname]["issues"] = issues
            except Exception as e:
                print(f"Error fetching issues for {pname}: {e}")

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
        except Exception as e:
            st.error(f"Error reading CSV: {str(e)}")

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


# --- PROCESS USERS ---
usernames = st.session_state.usernames


def process_users():
    for username in usernames:
        status = st.empty()
        user_container = st.container()

        if username in st.session_state.bulk_data:
            status.success(f"✅ {username} (cached)")
            continue

        try:
            status.info(f"⏳ Fetching {username}...")
            user, personal, contrib, contrib_data = gather_user_data_cached(username)
            st.session_state.bulk_data[username] = (user, personal, contrib, contrib_data)
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

            total_commits = total_mrs = total_issues = 0
            total_mr_comments = total_issue_comments = 0

            for pdata in contrib_data.values():
                total_commits += count_items_by_date(
                    pdata["commits"], "created_at", start_date, end_date
                )
                total_mrs += count_items_by_date(
                    pdata["mrs"], "created_at", start_date, end_date
                )
                total_issues += count_items_by_date(
                    pdata["issues"], "created_at", start_date, end_date
                )

                total_mr_comments += sum(m.get("user_comment_count", 0) for m in pdata["mrs"])
                total_issue_comments += sum(i.get("user_comment_count", 0) for i in pdata["issues"])

            st.write(f"📈 **Contributions ({start_date} → {end_date})**")
            c1, c2, c3 = st.columns(3)
            c1.metric("📝 Commits", total_commits)
            c2.metric("📦 Merge Requests", total_mrs)
            c3.metric("🐞 Issues", total_issues)

            c4, c5 = st.columns(2)
            c4.metric("💬 MR Comments", total_mr_comments)
            c5.metric("💬 Issue Comments", total_issue_comments)

            st.metric("🏆 Total Contributions", total_commits + total_mrs + total_issues)

            with st.expander("🔍 View Project Details"):
                for project_name, pdata in contrib_data.items():
                    pc = count_items_by_date(pdata["commits"], "created_at", start_date, end_date)
                    pm = count_items_by_date(pdata["mrs"], "created_at", start_date, end_date)
                    pi = count_items_by_date(pdata["issues"], "created_at", start_date, end_date)
                    pmc = sum(m.get("user_comment_count", 0) for m in pdata["mrs"])
                    pic = sum(i.get("user_comment_count", 0) for i in pdata["issues"])

                    if pc or pm or pi:
                        st.write(f"**{project_name}**")
                        st.write(f"- Commits: {pc}")
                        st.write(f"- Merge Requests: {pm} (💬 {pmc} comments)")
                        st.write(f"- Issues: {pi} (💬 {pic} comments)")
                        st.write("---")


if usernames:
    process_users()