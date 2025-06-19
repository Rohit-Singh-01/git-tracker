
# import streamlit as st
# import asyncio
# import aiohttp
# import pandas as pd
# from datetime import date
# import hashlib

# # --- CONFIG ---
# GITLAB_TOKEN = st.secrets["gitlab"]["token"]
# BASE_URL = st.secrets["gitlab"]["base_url"]
# STATE_PREFIX = "gitlab_tracker_"

# # Initialize session state keys if not present
# persistent_keys = {
#     f"{STATE_PREFIX}fetched_data": None,
#     f"{STATE_PREFIX}data_hash": None,
#     f"{STATE_PREFIX}avg_stats": None,
#     f"{STATE_PREFIX}filters": {
#         "grade_filter": "All Grades",
#         "metric_filter": "All Metrics"
#     }
# }
# for key, default_value in persistent_keys.items():
#     if key not in st.session_state:
#         st.session_state[key] = default_value

# # --- HASHING FOR CACHING ---
# def get_data_hash(usernames, start_date, end_date):
#     data_string = f"{','.join(sorted(usernames))}{start_date}{end_date}"
#     return hashlib.md5(data_string.encode()).hexdigest()

# # --- ASYNC HELPER FUNCTIONS ---
# async def fetch_json(session, url, params=None):
#     headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
#     async with session.get(url, headers=headers, params=params) as response:
#         if response.status == 200:
#             return await response.json()
#         return []

# async def fetch_json_with_pagination(session, url, params=None, max_pages=5):
#     headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
#     all_data = []
#     page = 1
#     while page <= max_pages:
#         current_params = (params or {}).copy()
#         current_params.update({"page": page, "per_page": 100})
#         async with session.get(url, headers=headers, params=current_params) as response:
#             if response.status != 200:
#                 break
#             data = await response.json()
#             if not data:
#                 break
#             all_data.extend(data)
#             link_header = response.headers.get('Link', '')
#             if 'rel="next"' not in link_header:
#                 break
#             page += 1
#     return all_data

# # --- USER & PROJECT FETCHING ---
# async def fetch_user_projects_optimized(session, user_id):
#     return await fetch_json_with_pagination(
#         session, f"{BASE_URL}/users/{user_id}/projects", params={"simple": "true"}
#     )

# async def fetch_contributed_projects_optimized(session, user_id):
#     return await fetch_json_with_pagination(
#         session, f"{BASE_URL}/users/{user_id}/contributed_projects", params={"simple": "true"}
#     )

# # --- CONTRIBUTION FETCHING ---
# async def fetch_commits(session, project_id, user_id, username, start_date, end_date):
#     """Fetch only commits authored by the specific user using multiple strategies"""
#     user_commits = []

#     # Strategy 1: Use author parameter with username
#     try:
#         commits = await fetch_json_with_pagination(
#             session,
#             f"{BASE_URL}/projects/{project_id}/repository/commits",
#             params={
#                 "author": username,
#                 "since": start_date.isoformat(),
#                 "until": end_date.isoformat()
#             },
#             max_pages=10
#         )
#         user_commits.extend(commits)
#     except Exception:
#         pass

#     # Strategy 2: Get user info and try with emails
#     try:
#         user_info = await fetch_json(session, f"{BASE_URL}/users/{user_id}")
#         user_emails = [email.lower() for email in [
#             user_info.get("email"),
#             user_info.get("public_email")
#         ] if email]
#         for email in user_emails:
#             try:
#                 commits = await fetch_json_with_pagination(
#                     session,
#                     f"{BASE_URL}/projects/{project_id}/repository/commits",
#                     params={
#                         "author_email": email,
#                         "since": start_date.isoformat(),
#                         "until": end_date.isoformat()
#                     },
#                     max_pages=10
#                 )
#                 user_commits.extend(commits)
#             except:
#                 continue
#     except:
#         pass

#     # Strategy 3: Fallback - Get all recent commits and filter manually
#     if not user_commits:
#         try:
#             all_commits = await fetch_json_with_pagination(
#                 session,
#                 f"{BASE_URL}/projects/{project_id}/repository/commits",
#                 params={
#                     "since": start_date.isoformat(),
#                     "until": end_date.isoformat()
#                 },
#                 max_pages=10
#             )
#             user_info = await fetch_json(session, f"{BASE_URL}/users/{user_id}")
#             user_name = user_info.get('name', '').lower()
#             user_username = user_info.get('username', '').lower()
#             user_emails = [email.lower() for email in [
#                 user_info.get('email', ''),
#                 user_info.get('public_email', '')
#             ] if email]

#             for commit in all_commits:
#                 author_name = commit.get('author_name', '').lower()
#                 author_email = commit.get('author_email', '').lower()
#                 committer_name = commit.get('committer_name', '').lower()
#                 committer_email = commit.get('committer_email', '').lower()

#                 name_match = (
#                     user_name in author_name or
#                     user_username in author_name or
#                     user_name in committer_name or
#                     user_username in committer_name
#                 )
#                 email_match = any(email in [author_email, committer_email] for email in user_emails)

#                 if name_match or email_match:
#                     user_commits.append(commit)
#         except:
#             pass

#     seen_ids = set()
#     unique_commits = []
#     for commit in user_commits:
#         if commit['id'] not in seen_ids:
#             seen_ids.add(commit['id'])
#             unique_commits.append(commit)
#     return unique_commits

# async def fetch_merge_requests(session, user_id, project_id, start_date, end_date):
#     return await fetch_json_with_pagination(
#         session,
#         f"{BASE_URL}/projects/{project_id}/merge_requests",
#         params={
#             "author_id": user_id,
#             "created_after": start_date.isoformat(),
#             "created_before": end_date.isoformat()
#         },
#         max_pages=5
#     )

# async def fetch_issues(session, user_id, project_id, start_date, end_date):
#     return await fetch_json_with_pagination(
#         session,
#         f"{BASE_URL}/projects/{project_id}/issues",
#         params={
#             "author_id": user_id,
#             "created_after": start_date.isoformat(),
#             "created_before": end_date.isoformat()
#         },
#         max_pages=5
#     )

# async def fetch_comments(session, project_id, item_type, item_iid, user_id):
#     notes = await fetch_json_with_pagination(
#         session,
#         f"{BASE_URL}/projects/{project_id}/{item_type}/{item_iid}/notes",
#         params={"per_page": 100},
#         max_pages=3
#     )
#     count = 0
#     for note in notes:
#         if note.get("author", {}).get("id") == user_id and not note.get("system", False) and note.get("body", "").strip():
#             count += 1
#     return count

# # --- MAIN DATA GATHERING FUNCTION ---
# async def gather_user_data(username, start_date, end_date, session, semaphore):
#     async with semaphore:
#         try:
#             # Fetch user info
#             user = await fetch_json(
#                 session, f"{BASE_URL}/users", params={"username": username}
#             )
#             if not user:
#                 return None
#             user = user[0]
#             user_id = user["id"]

#             # Fetch both personal and contributed projects
#             personal_projects = await fetch_user_projects_optimized(session, user_id)
#             contributed_projects = await fetch_contributed_projects_optimized(session, user_id)

#             # Combine and deduplicate
#             all_projects = {p['id']: p for p in personal_projects + contributed_projects}
#             projects_to_process = list(all_projects.values())[:50]

#             total_commits = 0
#             total_mrs = {"opened": 0, "closed": 0, "merged": 0, "total": 0}
#             total_issues = {"opened": 0, "closed": 0, "total": 0}
#             total_mr_comments = 0
#             total_issue_comments = 0

#             async def process_project(project):
#                 nonlocal total_commits, total_mrs, total_issues, total_mr_comments, total_issue_comments
#                 project_id = project["id"]
#                 try:
#                     # Get commits
#                     commits = await fetch_commits(session, project_id, user_id, username, start_date, end_date)
#                     total_commits += len(commits)

#                     # Get MRs
#                     mrs = await fetch_merge_requests(session, user_id, project_id, start_date, end_date)
#                     for mr in mrs:
#                         state = mr.get("state", "").lower()
#                         if state in total_mrs:
#                             total_mrs[state] += 1
#                     total_mrs["total"] += len(mrs)

#                     # Get Issues
#                     issues = await fetch_issues(session, user_id, project_id, start_date, end_date)
#                     for issue in issues:
#                         state = issue.get("state", "").lower()
#                         if state in total_issues:
#                             total_issues[state] += 1
#                     total_issues["total"] += len(issues)

#                     # Get MR Comments
#                     for mr in mrs:
#                         total_mr_comments += await fetch_comments(session, project_id, "merge_requests", mr["iid"], user_id)

#                     # Get Issue Comments
#                     for issue in issues:
#                         total_issue_comments += await fetch_comments(session, project_id, "issues", issue["iid"], user_id)

#                 except Exception:
#                     pass

#             tasks = [process_project(project) for project in projects_to_process]
#             await asyncio.gather(*tasks)

#             return {
#                 "username": user["username"],
#                 "name": user["name"],
#                 "commits": total_commits,
#                 "merge_requests": total_mrs["total"],
#                 "mrs_opened": total_mrs["opened"],
#                 "mrs_closed": total_mrs["closed"],
#                 "mrs_merged": total_mrs["merged"],
#                 "issues": total_issues["total"],
#                 "issues_opened": total_issues["opened"],
#                 "issues_closed": total_issues["closed"],
#                 "mr_comments": total_mr_comments,
#                 "issue_comments": total_issue_comments,
#                 "total_contributions": total_commits + total_mrs["total"] + total_issues["total"]
#             }

#         except Exception:
#             return None

# # --- GRADING LOGIC ---
# def calculate_grade(value, avg_value):
#     if avg_value == 0:
#         return "No Data" if value == 0 else "Above Average"
#     percentage = (value / avg_value) * 100
#     if percentage >= 135:
#         return "Excellent"
#     elif percentage >= 90:
#         return "Good"
#     elif percentage >= 50:
#         return "Average"
#     else:
#         return "Below Average"

# # --- CLEAN CSV DATA ---
# def clean_csv_data(df):
#     df = df.dropna(how='all')
#     df = df.dropna(subset=['username'])
#     df['username'] = df['username'].astype(str).str.strip()
#     df = df[df['username'] != '']
#     return df.reset_index(drop=True)

# # --- STREAMLIT UI ---
# st.set_page_config(page_title="GitLab Contribution Tracker", layout="wide")
# st.title("GitLab Author Contribution Tracker")

# uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
# if uploaded_file is not None:
#     try:
#         df_input = pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
#         if 'username' not in df_input.columns:
#             st.error("CSV must contain a 'username' column")
#         else:
#             df_input = clean_csv_data(df_input)
#             if len(df_input) == 0:
#                 st.warning("No valid usernames found in the CSV file")
#             else:
#                 st.success(f"Loaded {len(df_input)} students from CSV")
#                 st.dataframe(df_input.head(), use_container_width=True)

#                 col_start, col_end = st.columns(2)
#                 start_date = col_start.date_input("Start Date", value=date(2020, 1, 1))
#                 end_date = col_end.date_input("End Date", value=date.today())

#                 usernames = df_input['username'].tolist()
#                 current_hash = get_data_hash(usernames, start_date, end_date)
#                 cached_hash = st.session_state.get(f"{STATE_PREFIX}data_hash")

#                 if cached_hash == current_hash and st.session_state[f"{STATE_PREFIX}fetched_data"] is not None:
#                     st.info("Data already fetched for these parameters.")
#                     if st.button("Process Cached Data"):
#                         st.session_state[f"{STATE_PREFIX}show_results"] = True
#                         st.rerun()
#                     elif st.button("Force Refresh"):
#                         st.session_state[f"{STATE_PREFIX}fetched_data"] = None
#                         st.session_state[f"{STATE_PREFIX}data_hash"] = None
#                         st.cache_data.clear()
#                         st.rerun()
#                 elif st.button("Fetch Data"):
#                     BATCH_SIZE = 10
#                     SEMAPHORE_LIMIT = 10

#                     progress_bar = st.progress(0)
#                     status_text = st.empty()

#                     async def fetch_all_users():
#                         connector = aiohttp.TCPConnector(limit_per_host=10)
#                         async with aiohttp.ClientSession(connector=connector) as session:
#                             semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
#                             all_data = []

#                             for i in range(0, len(usernames), BATCH_SIZE):
#                                 batch = usernames[i:i+BATCH_SIZE]
#                                 tasks = [gather_user_data(u, start_date, end_date, session, semaphore) for u in batch]
#                                 results = await asyncio.gather(*tasks)
#                                 all_data.extend([r for r in results if r])
#                                 percent_complete = min((i + BATCH_SIZE) / len(usernames), 1.0)
#                                 progress_bar.progress(percent_complete)
#                                 status_text.text(f"Fetched {min(i + BATCH_SIZE, len(usernames))}/{len(usernames)} users...")
#                                 await asyncio.sleep(0.1)  # Give UI time to refresh
#                             return all_data

#                     loop = asyncio.new_event_loop()
#                     all_data = loop.run_until_complete(fetch_all_users())
#                     if all_data:
#                         df_results = pd.DataFrame(all_data)
#                         st.session_state[f"{STATE_PREFIX}fetched_data"] = df_results
#                         st.session_state[f"{STATE_PREFIX}data_hash"] = current_hash
#                         status_text.text("✅ Data fetching completed!")
#                     else:
#                         st.error("No data could be fetched.")

#                 fetched_data = st.session_state.get(f"{STATE_PREFIX}fetched_data")
#                 if fetched_data is not None:
#                     # Calculate Averages
#                     avg_metrics = {
#                         "commits": fetched_data["commits"].mean(),
#                         "merge_requests": fetched_data["merge_requests"].mean(),
#                         "issues": fetched_data["issues"].mean(),
#                         "total_contributions": fetched_data["total_contributions"].mean()
#                     }
#                     st.session_state[f"{STATE_PREFIX}avg_stats"] = avg_metrics

#                     # Apply Grading
#                     fetched_data["commit_grade"] = fetched_data["commits"].apply(lambda x: calculate_grade(x, avg_metrics["commits"]))
#                     fetched_data["mr_grade"] = fetched_data["merge_requests"].apply(lambda x: calculate_grade(x, avg_metrics["merge_requests"]))
#                     fetched_data["issue_grade"] = fetched_data["issues"].apply(lambda x: calculate_grade(x, avg_metrics["issues"]))
#                     fetched_data["contribution_grade"] = fetched_data["total_contributions"].apply(lambda x: calculate_grade(x, avg_metrics["total_contributions"]))

#                     # Filter Controls
#                     grade_options = ["All Grades", "Excellent", "Good", "Average", "Below Average"]
#                     selected_grade = st.selectbox("Filter by Grade", grade_options)
#                     metric_options = ["All Metrics", "Commits", "Merge Requests", "Issues", "Total Contributions"]
#                     selected_metric = st.selectbox("Select Metric to Filter", metric_options)

#                     # Apply Filter
#                     filtered_df = fetched_data.copy()
#                     if selected_grade != "All Grades":
#                         if selected_metric == "Commits":
#                             filtered_df = filtered_df[filtered_df["commit_grade"] == selected_grade]
#                         elif selected_metric == "Merge Requests":
#                             filtered_df = filtered_df[filtered_df["mr_grade"] == selected_grade]
#                         elif selected_metric == "Issues":
#                             filtered_df = filtered_df[filtered_df["issue_grade"] == selected_grade]
#                         elif selected_metric == "Total Contributions":
#                             filtered_df = filtered_df[filtered_df["contribution_grade"] == selected_grade]
#                         else:
#                             mask = ((filtered_df["commit_grade"] == selected_grade) |
#                                     (filtered_df["mr_grade"] == selected_grade) |
#                                     (filtered_df["issue_grade"] == selected_grade) |
#                                     (filtered_df["contribution_grade"] == selected_grade))
#                             filtered_df = filtered_df[mask]

#                     # Show Results
#                     st.subheader("Author Contributions")
#                     st.dataframe(filtered_df, hide_index=True, use_container_width=True)

#                     # Download Options
#                     csv_all = fetched_data.to_csv(index=False)
#                     csv_filtered = filtered_df.to_csv(index=False)
#                     col1, col2 = st.columns(2)
#                     with col1:
#                         st.download_button("Download Full CSV", data=csv_all, file_name="gitlab_full_contributions.csv", mime="text/csv")
#                     with col2:
#                         st.download_button("Download Filtered CSV", data=csv_filtered, file_name="gitlab_filtered_contributions.csv", mime="text/csv")

#                     # Reset Button
#                     if st.button("🔄 Reset All Data"):
#                         st.session_state[f"{STATE_PREFIX}fetched_data"] = None
#                         st.session_state[f"{STATE_PREFIX}data_hash"] = None
#                         st.session_state[f"{STATE_PREFIX}avg_stats"] = None
#                         st.session_state[f"{STATE_PREFIX}filters"] = {
#                             "grade_filter": "All Grades",
#                             "metric_filter": "All Metrics"
#                         }
#                         st.success("All data and settings have been reset.")
#     except Exception as e:
#         st.error(f"Error reading CSV: {str(e)}")






import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import date
import hashlib

# --- CONFIG ---
GITLAB_TOKEN = st.secrets["gitlab"]["token"]
BASE_URL = st.secrets["gitlab"]["base_url"]
STATE_PREFIX = "gitlab_tracker_"

# Initialize session state keys if not present
persistent_keys = {
    f"{STATE_PREFIX}fetched_data": None,
    f"{STATE_PREFIX}data_hash": None,
    f"{STATE_PREFIX}avg_stats": None,
    f"{STATE_PREFIX}filters": {
        "grade_filter": "All Grades",
        "metric_filter": "All Metrics"
    }
}
for key, default_value in persistent_keys.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# --- HASHING FOR CACHING ---
@st.cache_data(ttl=None)
def get_data_hash(usernames, start_date, end_date):
    data_string = f"{','.join(sorted(usernames))}{start_date}{end_date}"
    return hashlib.md5(data_string.encode()).hexdigest()

# --- ASYNC HELPER FUNCTIONS ---
async def fetch_json(session, url, params=None):
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    async with session.get(url, headers=headers, params=params) as response:
        if response.status == 200:
            return await response.json()
        return []

async def fetch_json_with_pagination(session, url, params=None, max_pages=5):
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    all_data = []
    page = 1
    while page <= max_pages:
        current_params = (params or {}).copy()
        current_params.update({"page": page, "per_page": 100})
        async with session.get(url, headers=headers, params=current_params) as response:
            if response.status != 200:
                break
            data = await response.json()
            if not data:
                break
            all_data.extend(data)
            link_header = response.headers.get('Link', '')
            if 'rel="next"' not in link_header:
                break
            page += 1
    return all_data

# --- USER & PROJECT FETCHING ---
async def fetch_user_projects_optimized(session, user_id):
    return await fetch_json_with_pagination(
        session, f"{BASE_URL}/users/{user_id}/projects", params={"simple": "true"}
    )

async def fetch_contributed_projects_optimized(session, user_id):
    return await fetch_json_with_pagination(
        session, f"{BASE_URL}/users/{user_id}/contributed_projects", params={"simple": "true"}
    )

# --- CONTRIBUTION FETCHING ---
async def fetch_commits(session, project_id, user_id, username, start_date, end_date):
    """Fetch only commits authored by the specific user using multiple strategies"""
    user_commits = []

    # Strategy 1: Use author parameter with username
    try:
        commits = await fetch_json_with_pagination(
            session,
            f"{BASE_URL}/projects/{project_id}/repository/commits",
            params={
                "author": username,
                "since": start_date.isoformat(),
                "until": end_date.isoformat()
            },
            max_pages=10
        )
        user_commits.extend(commits)
    except Exception:
        pass

    # Strategy 2: Get user info and try with emails
    try:
        user_info = await fetch_json(session, f"{BASE_URL}/users/{user_id}")
        user_emails = [email.lower() for email in [
            user_info.get("email"),
            user_info.get("public_email")
        ] if email]
        for email in user_emails:
            try:
                commits = await fetch_json_with_pagination(
                    session,
                    f"{BASE_URL}/projects/{project_id}/repository/commits",
                    params={
                        "author_email": email,
                        "since": start_date.isoformat(),
                        "until": end_date.isoformat()
                    },
                    max_pages=10
                )
                user_commits.extend(commits)
            except:
                continue
    except:
        pass

    # Strategy 3: Fallback - Get all recent commits and filter manually
    if not user_commits:
        try:
            all_commits = await fetch_json_with_pagination(
                session,
                f"{BASE_URL}/projects/{project_id}/repository/commits",
                params={
                    "since": start_date.isoformat(),
                    "until": end_date.isoformat()
                },
                max_pages=10
            )
            user_info = await fetch_json(session, f"{BASE_URL}/users/{user_id}")
            user_name = user_info.get('name', '').lower()
            user_username = user_info.get('username', '').lower()
            user_emails = [email.lower() for email in [
                user_info.get('email', ''),
                user_info.get('public_email', '')
            ] if email]

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
                email_match = any(email in [author_email, committer_email] for email in user_emails)

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

async def fetch_merge_requests(session, user_id, project_id, start_date, end_date):
    return await fetch_json_with_pagination(
        session,
        f"{BASE_URL}/projects/{project_id}/merge_requests",
        params={
            "author_id": user_id,
            "created_after": start_date.isoformat(),
            "created_before": end_date.isoformat()
        },
        max_pages=5
    )

async def fetch_issues(session, user_id, project_id, start_date, end_date):
    return await fetch_json_with_pagination(
        session,
        f"{BASE_URL}/projects/{project_id}/issues",
        params={
            "author_id": user_id,
            "created_after": start_date.isoformat(),
            "created_before": end_date.isoformat()
        },
        max_pages=5
    )

async def fetch_comments(session, project_id, item_type, item_iid, user_id):
    notes = await fetch_json_with_pagination(
        session,
        f"{BASE_URL}/projects/{project_id}/{item_type}/{item_iid}/notes",
        params={"per_page": 100},
        max_pages=3
    )
    count = 0
    for note in notes:
        if note.get("author", {}).get("id") == user_id and not note.get("system", False) and note.get("body", "").strip():
            count += 1
    return count

# --- MAIN DATA GATHERING FUNCTION ---
@st.cache_data(ttl=None)
def gather_all_user_data(usernames, start_date, end_date):
    """Cached wrapper for the async data gathering process"""
    async def gather_user_data(username, start_date, end_date, session, semaphore):
        async with semaphore:
            try:
                # Fetch user info
                user = await fetch_json(
                    session, f"{BASE_URL}/users", params={"username": username}
                )
                if not user:
                    return None
                user = user[0]
                user_id = user["id"]

                # Fetch both personal and contributed projects
                personal_projects = await fetch_user_projects_optimized(session, user_id)
                contributed_projects = await fetch_contributed_projects_optimized(session, user_id)

                # Combine and deduplicate
                all_projects = {p['id']: p for p in personal_projects + contributed_projects}
                projects_to_process = list(all_projects.values())[:50]

                total_commits = 0
                total_mrs = {"opened": 0, "closed": 0, "merged": 0, "total": 0}
                total_issues = {"opened": 0, "closed": 0, "total": 0}
                total_mr_comments = 0
                total_issue_comments = 0

                async def process_project(project):
                    nonlocal total_commits, total_mrs, total_issues, total_mr_comments, total_issue_comments
                    project_id = project["id"]
                    try:
                        # Get commits
                        commits = await fetch_commits(session, project_id, user_id, username, start_date, end_date)
                        total_commits += len(commits)

                        # Get MRs
                        mrs = await fetch_merge_requests(session, user_id, project_id, start_date, end_date)
                        for mr in mrs:
                            state = mr.get("state", "").lower()
                            if state in total_mrs:
                                total_mrs[state] += 1
                        total_mrs["total"] += len(mrs)

                        # Get Issues
                        issues = await fetch_issues(session, user_id, project_id, start_date, end_date)
                        for issue in issues:
                            state = issue.get("state", "").lower()
                            if state in total_issues:
                                total_issues[state] += 1
                        total_issues["total"] += len(issues)

                        # Get MR Comments
                        for mr in mrs:
                            total_mr_comments += await fetch_comments(session, project_id, "merge_requests", mr["iid"], user_id)

                        # Get Issue Comments
                        for issue in issues:
                            total_issue_comments += await fetch_comments(session, project_id, "issues", issue["iid"], user_id)

                    except Exception:
                        pass

                tasks = [process_project(project) for project in projects_to_process]
                await asyncio.gather(*tasks)

                return {
                    "username": user["username"],
                    "name": user["name"],
                    "commits": total_commits,
                    "merge_requests": total_mrs["total"],
                    "mrs_opened": total_mrs["opened"],
                    "mrs_closed": total_mrs["closed"],
                    "mrs_merged": total_mrs["merged"],
                    "issues": total_issues["total"],
                    "issues_opened": total_issues["opened"],
                    "issues_closed": total_issues["closed"],
                    "mr_comments": total_mr_comments,
                    "issue_comments": total_issue_comments,
                    "total_contributions": total_commits + total_mrs["total"] + total_issues["total"]
                }

            except Exception:
                return None

    async def fetch_all_users():
        BATCH_SIZE = 10
        SEMAPHORE_LIMIT = 10
        
        connector = aiohttp.TCPConnector(limit_per_host=10)
        async with aiohttp.ClientSession(connector=connector) as session:
            semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
            all_data = []

            for i in range(0, len(usernames), BATCH_SIZE):
                batch = usernames[i:i+BATCH_SIZE]
                tasks = [gather_user_data(u, start_date, end_date, session, semaphore) for u in batch]
                results = await asyncio.gather(*tasks)
                all_data.extend([r for r in results if r])
                await asyncio.sleep(0.1)  # Give UI time to refresh
            return all_data

    loop = asyncio.new_event_loop()
    return loop.run_until_complete(fetch_all_users())

# --- GRADING LOGIC ---
@st.cache_data(ttl=None)
def calculate_grade(value, avg_value):
    if avg_value == 0:
        return "No Data" if value == 0 else "Above Average"
    percentage = (value / avg_value) * 100
    if percentage >= 135:
        return "Excellent"
    elif percentage >= 90:
        return "Good"
    elif percentage >= 50:
        return "Average"
    else:
        return "Below Average"

# --- CLEAN CSV DATA ---
@st.cache_data(ttl=None)
def clean_csv_data(df):
    df = df.dropna(how='all')
    df = df.dropna(subset=['username'])
    df['username'] = df['username'].astype(str).str.strip()
    df = df[df['username'] != '']
    return df.reset_index(drop=True)

# --- PROCESS AND GRADE DATA ---
@st.cache_data(ttl=None)
def process_and_grade_data(df_results):
    """Process the results dataframe and add grades"""
    # Calculate Averages
    avg_metrics = {
        "commits": df_results["commits"].mean(),
        "merge_requests": df_results["merge_requests"].mean(),
        "issues": df_results["issues"].mean(),
        "total_contributions": df_results["total_contributions"].mean()
    }

    # Apply Grading
    df_results["commit_grade"] = df_results["commits"].apply(lambda x: calculate_grade(x, avg_metrics["commits"]))
    df_results["mr_grade"] = df_results["merge_requests"].apply(lambda x: calculate_grade(x, avg_metrics["merge_requests"]))
    df_results["issue_grade"] = df_results["issues"].apply(lambda x: calculate_grade(x, avg_metrics["issues"]))
    df_results["contribution_grade"] = df_results["total_contributions"].apply(lambda x: calculate_grade(x, avg_metrics["total_contributions"]))

    return df_results, avg_metrics

# --- DISPLAY STATISTICS ---
def display_statistics_and_top_contributors(df_results, avg_metrics):
    """Display average statistics and top contributors"""
    
    # Statistics Section
    st.subheader("📊 Overall Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="Average Commits",
            value=f"{avg_metrics['commits']:.1f}",
            delta=f"Total: {df_results['commits'].sum()}"
        )
    
    with col2:
        st.metric(
            label="Average Merge Requests",
            value=f"{avg_metrics['merge_requests']:.1f}",
            delta=f"Total: {df_results['merge_requests'].sum()}"
        )
    
    with col3:
        st.metric(
            label="Average Issues",
            value=f"{avg_metrics['issues']:.1f}",
            delta=f"Total: {df_results['issues'].sum()}"
        )
    
    with col4:
        st.metric(
            label="Average Total Contributions",
            value=f"{avg_metrics['total_contributions']:.1f}",
            delta=f"Total: {df_results['total_contributions'].sum()}"
        )
    
    # Top Contributors Section
    st.subheader("🏆 Top Contributors")
    
    # Create tabs for different metrics
    tab1, tab2, tab3, tab4 = st.tabs(["🔀 Total Contributions", "💻 Commits", "🔄 Merge Requests", "❗ Issues"])
    
    with tab1:
        top_total = df_results.nlargest(10, 'total_contributions')[['username', 'name', 'total_contributions', 'contribution_grade']]
        top_total = top_total.rename(columns={
            'username': 'Username',
            'name': 'Name', 
            'total_contributions': 'Total Contributions',
            'contribution_grade': 'Grade'
        })
        st.dataframe(top_total, hide_index=True, use_container_width=True)
    
    with tab2:
        top_commits = df_results.nlargest(10, 'commits')[['username', 'name', 'commits', 'commit_grade']]
        top_commits = top_commits.rename(columns={
            'username': 'Username',
            'name': 'Name',
            'commits': 'Commits',
            'commit_grade': 'Grade'
        })
        st.dataframe(top_commits, hide_index=True, use_container_width=True)
    
    with tab3:
        top_mrs = df_results.nlargest(10, 'merge_requests')[['username', 'name', 'merge_requests', 'mr_grade']]
        top_mrs = top_mrs.rename(columns={
            'username': 'Username',
            'name': 'Name',
            'merge_requests': 'Merge Requests',
            'mr_grade': 'Grade'
        })
        st.dataframe(top_mrs, hide_index=True, use_container_width=True)
    
    with tab4:
        top_issues = df_results.nlargest(10, 'issues')[['username', 'name', 'issues', 'issue_grade']]
        top_issues = top_issues.rename(columns={
            'username': 'Username',
            'name': 'Name',
            'issues': 'Issues',
            'issue_grade': 'Grade'
        })
        st.dataframe(top_issues, hide_index=True, use_container_width=True)

# --- STREAMLIT UI ---
st.set_page_config(page_title="GitLab Contribution Tracker", layout="wide")
st.title("GitLab Author Contribution Tracker")

uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
if uploaded_file is not None:
    try:
        df_input = pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
        if 'username' not in df_input.columns:
            st.error("CSV must contain a 'username' column")
        else:
            df_input = clean_csv_data(df_input)
            if len(df_input) == 0:
                st.warning("No valid usernames found in the CSV file")
            else:
                st.success(f"Loaded {len(df_input)} students from CSV")
                st.dataframe(df_input.head(), use_container_width=True)

                col_start, col_end = st.columns(2)
                start_date = col_start.date_input("Start Date", value=date(2020, 1, 1))
                end_date = col_end.date_input("End Date", value=date.today())

                usernames = df_input['username'].tolist()
                current_hash = get_data_hash(usernames, start_date, end_date)
                cached_hash = st.session_state.get(f"{STATE_PREFIX}data_hash")

                if cached_hash == current_hash and st.session_state[f"{STATE_PREFIX}fetched_data"] is not None:
                    st.info("Data already fetched for these parameters.")
                    if st.button("Process Cached Data"):
                        st.session_state[f"{STATE_PREFIX}show_results"] = True
                        st.rerun()
                    elif st.button("Force Refresh"):
                        st.session_state[f"{STATE_PREFIX}fetched_data"] = None
                        st.session_state[f"{STATE_PREFIX}data_hash"] = None
                        st.cache_data.clear()
                        st.rerun()
                elif st.button("Fetch Data"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    status_text.text("Fetching data from GitLab API...")
                    progress_bar.progress(0.1)
                    
                    # Use cached function for data gathering
                    all_data = gather_all_user_data(usernames, start_date, end_date)
                    
                    progress_bar.progress(0.9)
                    status_text.text("Processing results...")
                    
                    if all_data:
                        df_results = pd.DataFrame(all_data)
                        st.session_state[f"{STATE_PREFIX}fetched_data"] = df_results
                        st.session_state[f"{STATE_PREFIX}data_hash"] = current_hash
                        progress_bar.progress(1.0)
                        status_text.text("✅ Data fetching completed!")
                    else:
                        st.error("No data could be fetched.")

                fetched_data = st.session_state.get(f"{STATE_PREFIX}fetched_data")
                if fetched_data is not None:
                    # Process and grade data using cached function
                    processed_data, avg_metrics = process_and_grade_data(fetched_data.copy())
                    st.session_state[f"{STATE_PREFIX}avg_stats"] = avg_metrics

                    # Filter Controls
                    grade_options = ["All Grades", "Excellent", "Good", "Average", "Below Average"]
                    selected_grade = st.selectbox("Filter by Grade", grade_options)
                    metric_options = ["All Metrics", "Commits", "Merge Requests", "Issues", "Total Contributions"]
                    selected_metric = st.selectbox("Select Metric to Filter", metric_options)

                    # Apply Filter
                    filtered_df = processed_data.copy()
                    if selected_grade != "All Grades":
                        if selected_metric == "Commits":
                            filtered_df = filtered_df[filtered_df["commit_grade"] == selected_grade]
                        elif selected_metric == "Merge Requests":
                            filtered_df = filtered_df[filtered_df["mr_grade"] == selected_grade]
                        elif selected_metric == "Issues":
                            filtered_df = filtered_df[filtered_df["issue_grade"] == selected_grade]
                        elif selected_metric == "Total Contributions":
                            filtered_df = filtered_df[filtered_df["contribution_grade"] == selected_grade]
                        else:
                            mask = ((filtered_df["commit_grade"] == selected_grade) |
                                    (filtered_df["mr_grade"] == selected_grade) |
                                    (filtered_df["issue_grade"] == selected_grade) |
                                    (filtered_df["contribution_grade"] == selected_grade))
                            filtered_df = filtered_df[mask]

                    # Show Results
                    st.subheader("Author Contributions")
                    st.dataframe(filtered_df, hide_index=True, use_container_width=True)

                    # Display Statistics and Top Contributors
                    display_statistics_and_top_contributors(processed_data, avg_metrics)

                    # Download Options
                    csv_all = processed_data.to_csv(index=False)
                    csv_filtered = filtered_df.to_csv(index=False)
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button("Download Full CSV", data=csv_all, file_name="gitlab_full_contributions.csv", mime="text/csv")
                    with col2:
                        st.download_button("Download Filtered CSV", data=csv_filtered, file_name="gitlab_filtered_contributions.csv", mime="text/csv")

                    # Reset Button
                    if st.button("🔄 Reset All Data"):
                        st.session_state[f"{STATE_PREFIX}fetched_data"] = None
                        st.session_state[f"{STATE_PREFIX}data_hash"] = None
                        st.session_state[f"{STATE_PREFIX}avg_stats"] = None
                        st.session_state[f"{STATE_PREFIX}filters"] = {
                            "grade_filter": "All Grades",
                            "metric_filter": "All Metrics"
                        }
                        st.success("All data and settings have been reset.")
    except Exception as e:
        st.error(f"Error reading CSV: {str(e)}")