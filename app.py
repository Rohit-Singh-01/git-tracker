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


# --- CACHE WRAPPER FOR gather_data ---
@st.cache_data(ttl=None, show_spinner=False) 
def cached_gather_data(username):
    return asyncio.run(_gather_data(username))


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
    """Fetch only commits authored by the specific user using multiple strategies"""
    user_commits = []
    # Strategy 1: Use author parameter with username
    try:
        commits = await fetch_json(
            session,
            f"{BASE_URL}/projects/{project_id}/repository/commits",
            params={"author": username, "per_page": 100},
        )
        user_commits.extend(commits)
    except:
        pass
    # Strategy 2: Get user info and try with email
    try:
        user_info = await fetch_json(session, f"{BASE_URL}/users/{user_id}")
        user_emails = [user_info.get('email'), user_info.get('public_email')]
        user_emails = [email for email in user_emails if email]
        for email in user_emails:
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
            user_emails = [user_info.get('email', ''), user_info.get('public_email', '')]
            user_emails = [email.lower() for email in user_emails if email]
            for commit in all_commits:
                author_name = commit.get('author_name', '').lower()
                author_email = commit.get('author_email', '').lower()
                committer_name = commit.get('committer_name', '').lower()
                committer_email = commit.get('committer_email', '').lower()
                name_match = (user_name in author_name or
                              user_username in author_name or
                              user_name in committer_name or
                              user_username in committer_name)
                email_match = any(email in [author_email, committer_email] for email in user_emails)
                if name_match or email_match:
                    user_commits.append(commit)
        except:
            pass
    # Remove duplicates based on commit ID
    seen_ids = set()
    unique_commits = []
    for commit in user_commits:
        if commit['id'] not in seen_ids:
            seen_ids.add(commit['id'])
            unique_commits.append(commit)
    return unique_commits


async def fetch_merge_requests(session, user_id, project_id):
    """Fetch merge requests authored by the specific user only"""
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
    """Fetch issues authored by the specific user only"""
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
        # Filter comments by the specific user and exclude system notes (like status updates)
        user_comments = [
            comment for comment in all_comments
            if comment.get("author", {}).get("id") == user_id and comment.get("system", False) is False
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
            if comment.get("author", {}).get("id") == user_id and comment.get("system", False) is False
        ]
        return user_comments
    except Exception as e:
        print(f"Error fetching MR comments: {e}")
        return []


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
async def _gather_data(username):
    try:
        async with aiohttp.ClientSession() as session:
            user = await fetch_user(session, username)
            if not user:
                raise ValueError("User not found.")
            user_id = user["id"]
            username = user["username"]
            user_email = user.get("public_email") or user.get("email", "")
            personal_projects = await fetch_user_projects(session, user_id)
            contributed_projects = await fetch_contributed_projects(session, user_id)
            # Combine both personal and contributed projects
            all_projects = personal_projects + contributed_projects
            # Remove duplicates based on project ID
            unique_projects = {}
            for project in all_projects:
                project_id = project["id"]
                if project_id not in unique_projects:
                    # Add a flag to identify project type
                    project["is_personal"] = project in personal_projects
                    unique_projects[project_id] = project
            all_unique_projects = list(unique_projects.values())
            contrib_data = {}
            for project in all_unique_projects:
                project_id = project["id"]
                name = project["name_with_namespace"]
                contrib_data[name] = {"commits": [], "mrs": [], "issues": []}
                try:
                    # Fetch only commits by the specific user
                    commits = await fetch_commits(session, project_id, user_id, username)
                    contrib_data[name]["commits"] = commits
                except Exception as e:
                    print(f"Error fetching commits for {name}: {e}")
                try:
                    # Fetch only MRs created by the specific user
                    mrs = await fetch_merge_requests(session, user_id, project_id)
                    for mr in mrs:
                        try:
                            # Fetch only comments made by the specific user
                            user_comments = await fetch_mr_comments(session, project_id, mr["iid"], user_id)
                            mr["user_comment_count"] = len(user_comments)
                        except Exception as e:
                            print(f"Error fetching MR comments for {name}: {e}")
                            mr["user_comment_count"] = 0
                    contrib_data[name]["mrs"] = mrs
                except Exception as e:
                    print(f"Error fetching MRs for {name}: {e}")
                try:
                    # Fetch only issues created by the specific user
                    issues = await fetch_issues(session, user_id, project_id)
                    for issue in issues:
                        try:
                            # Fetch only comments made by the specific user
                            user_comments = await fetch_issue_comments(session, project_id, issue["iid"], user_id)
                            issue["user_comment_count"] = len(user_comments)
                        except Exception as e:
                            print(f"Error fetching issue comments for {name}: {e}")
                            issue["user_comment_count"] = 0
                    contrib_data[name]["issues"] = issues
                except Exception as e:
                    print(f"Error fetching issues for {name}: {e}")
            # Ensure we always return exactly 5 values
            return user, personal_projects, contributed_projects, all_unique_projects, contrib_data
    except Exception as e:
        raise e


# --- STREAMLIT UI ---
st.title("📊 GitLab Personal + Contribution Tracker")
st.caption("🔍 Shows only YOUR contributions in each project")

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
            result = cached_gather_data(username)
            if len(result) != 5:
                st.error(f"❌ Unexpected data structure returned. Expected 5 values, got {len(result)}")
            else:
                st.session_state.fetched_user_data = result
                st.session_state.fetched_username = username
                st.success(f"✅ Successfully fetched data for @{username}")
        except Exception as e:
            st.error(f"❌ {str(e)}")
            st.info("Make sure your GitLab token has correct access and base_url is valid.")

# Show data if stored in session
if st.session_state.fetched_user_data:
    try:
        user, personal_projects, contributed_projects, all_projects, contrib_data = (
            st.session_state.fetched_user_data
        )
    except ValueError as e:
        st.error(f"❌ Data structure error: {str(e)}")
        st.error("Please reset the data and try again.")
        if st.button("🔄 Auto Reset"):
            st.session_state.fetched_user_data = None
            st.session_state.fetched_username = None
            st.rerun()
    else:
        st.subheader(f"👤 {user['name']} (@{user['username']})")
        st.info(f"📧 Email: {user.get('public_email') or user.get('email', 'Not available')}")
        st.subheader("📁 Projects Summary")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Personal Projects", len(personal_projects))
        col2.metric("Contributed Projects", len(contributed_projects))
        col3.metric("All Projects", len(all_projects))
        col4.metric("Unique Projects", len(set(p["id"] for p in all_projects)))
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
                i.get("user_comment_count", 0) for i in pdata.get("issues", [])
            )
            total_mr_comments += sum(
                m.get("user_comment_count", 0) for m in pdata.get("mrs", [])
            )
        st.subheader(f"📈 Your Total Contributions ({start_date} → {end_date})")
        st.caption("📊 Combined from all your personal and contributed projects")
        c1, c2, c3 = st.columns(3)
        c1.metric("📝 Your Commits", total_commits)
        c2.metric("📦 Your Merge Requests", total_mrs)
        c3.metric("🐞 Your Issues", total_issues)
        c4, c5, c6 = st.columns(3)
        c4.metric("💬 Your MR Comments", total_mr_comments)
        c5.metric("💬 Your Issue Comments", total_issue_comments)
        c6.metric("🏆 Total Your Contributions", total_commits + total_mrs + total_issues)
        if contrib_data:
            with st.expander("🔍 View All Your Project Contributions"):
                # Separate personal and contributed projects for better organization
                personal_contrib = {}
                contributed_contrib = {}
                for project_name, pdata in contrib_data.items():
                    # Find project type
                    is_personal = False
                    for proj in all_projects:
                        if proj["name_with_namespace"] == project_name:
                            is_personal = proj.get("is_personal", False)
                            break
                    if is_personal:
                        personal_contrib[project_name] = pdata
                    else:
                        contributed_contrib[project_name] = pdata
                # Display personal projects first
                if personal_contrib:
                    st.markdown("### 👤 Your Personal Projects")
                    for project_name, pdata in personal_contrib.items():
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
                            i.get("user_comment_count", 0) for i in pdata.get("issues", [])
                        )
                        mr_comments = sum(
                            m.get("user_comment_count", 0) for m in pdata.get("mrs", [])
                        )
                        if sc or sm or si or issue_comments or mr_comments:
                            st.markdown(f"**{project_name}** 🏠")
                            st.write(f"- Your Commits: {sc}")
                            st.write(f"- Your Merge Requests: {sm} (💬 {mr_comments} your comments)")
                            st.write(f"- Your Issues: {si} (💬 {issue_comments} your comments)")
                            st.write("---")
                # Display contributed projects
                if contributed_contrib:
                    st.markdown("### 🤝 Projects You've Contributed To")
                    for project_name, pdata in contributed_contrib.items():
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
                            i.get("user_comment_count", 0) for i in pdata.get("issues", [])
                        )
                        mr_comments = sum(
                            m.get("user_comment_count", 0) for m in pdata.get("mrs", [])
                        )
                        if sc or sm or si or issue_comments or mr_comments:
                            st.markdown(f"**{project_name}** 🤝")
                            st.write(f"- Your Commits: {sc}")
                            st.write(f"- Your Merge Requests: {sm} (💬 {mr_comments} your comments)")
                            st.write(f"- Your Issues: {si} (💬 {issue_comments} your comments)")
                            st.write("---")
        # Debug summary with user-specific data
        if st.checkbox("🔍 Show Your Contribution Details with Links", key="debug_summary_checkbox_app"):
            st.subheader(f"📋 {user['username']}'s Detailed Contribution Summary with GitLab Links")
            # Separate personal and contributed projects
            personal_projects_data = []
            contributed_projects_data = []
            for project_name, pdata in contrib_data.items():
                project_info = None
                for proj in all_projects:
                    if proj["name_with_namespace"] == project_name:
                        project_info = proj
                        break
                if project_info:
                    project_data = {
                        'name': project_name,
                        'data': pdata,
                        'web_url': project_info['web_url'],
                        'is_personal': project_info.get('is_personal', False)
                    }
                    if project_info.get('is_personal', False):
                        personal_projects_data.append(project_data)
                    else:
                        contributed_projects_data.append(project_data)
            # Display personal projects
            if personal_projects_data:
                st.markdown("### 👤 Your Personal Projects")
                for proj_data in personal_projects_data:
                    project_name = proj_data['name']
                    pdata = proj_data['data']
                    web_url = proj_data['web_url']
                    num_commits = len(pdata.get("commits", []))
                    num_mrs = len(pdata.get("mrs", []))
                    num_issues = len(pdata.get("issues", []))
                    total_mr_comments = sum(m.get("user_comment_count", 0) for m in pdata["mrs"])
                    total_issue_comments = sum(i.get("user_comment_count", 0) for i in pdata["issues"])
                    if num_commits or num_mrs or num_issues or total_mr_comments or total_issue_comments:
                        st.markdown(f"#### 🏠 [{project_name}]({web_url})")
                        st.write(f"🔹 **Your Commits**: {num_commits}")
                        if num_commits:
                            latest_commit = pdata['commits'][0]
                            commit_url = f"{web_url}/-/commit/{latest_commit['id']}"
                            st.write(f"  🕒 [Latest Commit]({commit_url}): `{latest_commit.get('title', 'No title')}`")
                        st.write(f"🔸 **Your Merge Requests**: {num_mrs} (💬 {total_mr_comments} your comments)")
                        if num_mrs:
                            latest_mr = pdata['mrs'][0]
                            mr_url = f"{web_url}/-/merge_requests/{latest_mr['iid']}"
                            st.write(f"  🕒 [Latest MR]({mr_url}): `{latest_mr.get('title', 'No title')}` → `{latest_mr.get('state')}`")
                        st.write(f"🔻 **Your Issues**: {num_issues} (💬 {total_issue_comments} your comments)")
                        st.markdown("---")
            # Display contributed projects
            if contributed_projects_data:
                st.markdown("### 🤝 Projects You've Contributed To")
                for proj_data in contributed_projects_data:
                    project_name = proj_data['name']
                    pdata = proj_data['data']
                    web_url = proj_data['web_url']
                    num_commits = len(pdata.get("commits", []))
                    num_mrs = len(pdata.get("mrs", []))
                    num_issues = len(pdata.get("issues", []))
                    total_mr_comments = sum(m.get("user_comment_count", 0) for m in pdata["mrs"])
                    total_issue_comments = sum(i.get("user_comment_count", 0) for i in pdata["issues"])
                    if num_commits or num_mrs or num_issues or total_mr_comments or total_issue_comments:
                        st.markdown(f"#### 🤝 [{project_name}]({web_url})")
                        st.write(f"🔹 **Your Commits**: {num_commits}")
                        if num_commits:
                            latest_commit = pdata['commits'][0]
                            commit_url = f"{web_url}/-/commit/{latest_commit['id']}"
                            st.write(f"  🕒 [Latest Commit]({commit_url}): `{latest_commit.get('title', 'No title')}`")
                        st.write(f"🔸 **Your Merge Requests**: {num_mrs} (💬 {total_mr_comments} your comments)")
                        if num_mrs:
                            latest_mr = pdata['mrs'][0]
                            mr_url = f"{web_url}/-/merge_requests/{latest_mr['iid']}"
                            st.write(f"  🕒 [Latest MR]({mr_url}): `{latest_mr.get('title', 'No title')}` → `{latest_mr.get('state')}`")
                        st.write(f"🔻 **Your Issues**: {num_issues} (💬 {total_issue_comments} your comments)")
                        st.markdown("---")





