
import streamlit as st
import asyncio
import aiohttp
from datetime import datetime, timedelta
from dateutil import parser
import pandas as pd
import re
import hashlib
import json

# --- CONFIG ---
GITLAB_TOKEN = st.secrets["gitlab"]["token"]
BASE_URL = st.secrets["gitlab"]["base_url"]

# Cache TTL (Time To Live) in seconds - 1 hour
CACHE_TTL = 3600

# Initialize session state
if "user_data" not in st.session_state:
    st.session_state.user_data = None
if "projects_data" not in st.session_state:
    st.session_state.projects_data = None
if "commits_data" not in st.session_state:
    st.session_state.commits_data = None
if "merge_requests_data" not in st.session_state:
    st.session_state.merge_requests_data = None
if "issues_data" not in st.session_state:
    st.session_state.issues_data = None
if "mr_comments_data" not in st.session_state:
    st.session_state.mr_comments_data = None
if "issue_comments_data" not in st.session_state:
    st.session_state.issue_comments_data = None
if "last_username" not in st.session_state:
    st.session_state.last_username = ""
if "cache" not in st.session_state:
    st.session_state.cache = {}
if "cache_timestamps" not in st.session_state:
    st.session_state.cache_timestamps = {}

# --- CACHE FUNCTIONS ---
def get_cache_key(username, endpoint):
    """Generate a cache key for API responses"""
    return hashlib.md5(f"{username}_{endpoint}".encode()).hexdigest()

def is_cache_valid(cache_key):
    """Check if cached data is still valid"""
    if cache_key not in st.session_state.cache_timestamps:
        return False
    
    cache_time = st.session_state.cache_timestamps[cache_key]
    return (datetime.now() - cache_time).seconds < CACHE_TTL

def get_from_cache(cache_key):
    """Get data from cache if valid"""
    if is_cache_valid(cache_key):
        return st.session_state.cache.get(cache_key)
    return None

def save_to_cache(cache_key, data):
    """Save data to cache with timestamp"""
    st.session_state.cache[cache_key] = data
    st.session_state.cache_timestamps[cache_key] = datetime.now()

def clear_cache():
    """Clear all cached data"""
    st.session_state.cache = {}
    st.session_state.cache_timestamps = {}

def reset_all_data():
    """Reset all session state data"""
    st.session_state.user_data = None
    st.session_state.projects_data = None
    st.session_state.commits_data = None
    st.session_state.merge_requests_data = None
    st.session_state.issues_data = None
    st.session_state.mr_comments_data = None
    st.session_state.issue_comments_data = None
    st.session_state.last_username = ""
    clear_cache()

# --- API FETCH FUNCTIONS ---
async def fetch_json(session, url, params=None):
    """Async API fetch with proper error handling"""
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    async with session.get(url, headers=headers, params=params) as response:
        if response.status == 401:
            raise Exception("❌ Unauthorized: Check your GitLab token or permissions.")
        if response.status == 404:
            return None
        response.raise_for_status()
        return await response.json()

async def fetch_user(session, username):
    """Fetch user information by username"""
    users = await fetch_json(
        session, f"{BASE_URL}/users", params={"username": username}
    )
    return users[0] if users else None

async def fetch_projects(session, user_id):
    """Fetch projects owned by user"""
    try:
        return await fetch_json(session, f"{BASE_URL}/users/{user_id}/projects", params={"per_page": 100})
    except:
        return []

async def fetch_contributed_projects(session, user_id):
    """Fetch projects user has contributed to"""
    try:
        return await fetch_json(
            session,
            f"{BASE_URL}/users/{user_id}/contributed_projects",
            params={"per_page": 100},
        )
    except:
        return []

async def fetch_all_accessible_projects(session):
    """Fetch all projects the token has access to"""
    try:
        return await fetch_json(session, f"{BASE_URL}/projects", params={"per_page": 100, "membership": "true"})
    except:
        return []

def is_commit_by_author(commit, user_id, username, user_email, user_name):
    """Enhanced check if commit is authored by the specific user"""
    author_name = commit.get("author_name", "").lower().strip()
    author_email = commit.get("author_email", "").lower().strip()
    committer_name = commit.get("committer_name", "").lower().strip()
    committer_email = commit.get("committer_email", "").lower().strip()
    
    username_lower = username.lower().strip()
    user_email_lower = user_email.lower().strip() if user_email else ""
    user_name_lower = user_name.lower().strip() if user_name else ""
    
    # Check exact matches first
    if user_email_lower and (author_email == user_email_lower or committer_email == user_email_lower):
        return True
    
    # Check name matches
    if author_name == username_lower or committer_name == username_lower:
        return True
    
    if user_name_lower and (author_name == user_name_lower or committer_name == user_name_lower):
        return True
    
    # Check for partial name matches (e.g., "John Smith" vs "john.smith")
    if user_name_lower:
        name_parts = user_name_lower.split()
        if len(name_parts) >= 2:
            first_name = name_parts[0]
            last_name = name_parts[-1]
            if (first_name in author_name and last_name in author_name) or \
               (first_name in committer_name and last_name in committer_name):
                return True
    
    return False

async def fetch_commits_by_author(session, project_id, user_id, username, user_email, user_name, project_name):
    """Fetch commits by author with multiple strategies and proper filtering"""
    cache_key = get_cache_key(f"commits_{project_id}_{user_id}", "")
    cached_commits = get_from_cache(cache_key)
    
    if cached_commits is not None:
        return cached_commits
    
    verified_commits = []
    
    try:
        # Strategy 1: Use author_id parameter (most reliable if supported)
        try:
            commits = await fetch_json(
                session,
                f"{BASE_URL}/projects/{project_id}/repository/commits",
                params={"author_id": user_id, "per_page": 100, "all": "true"},
            )
            if commits:
                for commit in commits:
                    if is_commit_by_author(commit, user_id, username, user_email, user_name):
                        commit['project_name'] = project_name
                        verified_commits.append(commit)
        except Exception:
            pass
        
        # Strategy 2: Use author parameter with username
        if not verified_commits:
            try:
                commits = await fetch_json(
                    session,
                    f"{BASE_URL}/projects/{project_id}/repository/commits",
                    params={"author": username, "per_page": 100, "all": "true"},
                )
                if commits:
                    for commit in commits:
                        if is_commit_by_author(commit, user_id, username, user_email, user_name):
                            commit['project_name'] = project_name
                            verified_commits.append(commit)
            except Exception:
                pass
        
        # Strategy 3: Use author email if available
        if not verified_commits and user_email:
            try:
                commits = await fetch_json(
                    session,
                    f"{BASE_URL}/projects/{project_id}/repository/commits",
                    params={"author_email": user_email, "per_page": 100, "all": "true"},
                )
                if commits:
                    for commit in commits:
                        if is_commit_by_author(commit, user_id, username, user_email, user_name):
                            commit['project_name'] = project_name
                            verified_commits.append(commit)
            except Exception:
                pass
        
        # Strategy 4: Fetch recent commits and filter manually (last resort)
        if not verified_commits:
            try:
                all_commits = await fetch_json(
                    session,
                    f"{BASE_URL}/projects/{project_id}/repository/commits",
                    params={"per_page": 50, "all": "true"},
                )
                if all_commits:
                    for commit in all_commits:
                        if is_commit_by_author(commit, user_id, username, user_email, user_name):
                            commit['project_name'] = project_name
                            verified_commits.append(commit)
            except Exception:
                pass
    
    except Exception:
        pass
    
    # Remove duplicates based on commit ID
    seen_ids = set()
    unique_commits = []
    for commit in verified_commits:
        if commit['id'] not in seen_ids:
            seen_ids.add(commit['id'])
            unique_commits.append(commit)
    
    # Cache the results
    save_to_cache(cache_key, unique_commits)
    return unique_commits

async def fetch_merge_requests_by_author(session, user_id):
    """Fetch merge requests authored by the specific user across all projects"""
    cache_key = get_cache_key(f"mrs_{user_id}", "")
    cached_mrs = get_from_cache(cache_key)
    
    if cached_mrs is not None:
        return cached_mrs
    
    try:
        merge_requests = await fetch_json(
            session,
            f"{BASE_URL}/merge_requests",
            params={"author_id": user_id, "scope": "all", "per_page": 100},
        )
        
        # Filter to ensure they're actually authored by this user
        user_mrs = []
        if merge_requests:
            for mr in merge_requests:
                if mr.get("author", {}).get("id") == user_id:
                    user_mrs.append(mr)
        
        save_to_cache(cache_key, user_mrs)
        return user_mrs
    except Exception:
        return []

async def fetch_issues_by_author(session, user_id):
    """Fetch issues created by the specific user across all projects"""
    cache_key = get_cache_key(f"issues_{user_id}", "")
    cached_issues = get_from_cache(cache_key)
    
    if cached_issues is not None:
        return cached_issues
    
    try:
        issues = await fetch_json(
            session,
            f"{BASE_URL}/issues",
            params={"author_id": user_id, "scope": "all", "per_page": 100},
        )
        
        # Filter to ensure they're actually authored by this user
        user_issues = []
        if issues:
            for issue in issues:
                if issue.get("author", {}).get("id") == user_id:
                    user_issues.append(issue)
        
        save_to_cache(cache_key, user_issues)
        return user_issues
    except Exception:
        return []

async def fetch_mr_comments_by_user(session, user_id, projects):
    """Fetch ALL comments made by user on merge requests across accessible projects"""
    cache_key = get_cache_key(f"mr_comments_{user_id}", "")
    cached_comments = get_from_cache(cache_key)
    
    if cached_comments is not None:
        return cached_comments
    
    user_comments = []
    
    # Limit to first 20 projects for performance
    limited_projects = projects[:20] if len(projects) > 20 else projects
    
    for project in limited_projects:
        try:
            project_id = project["id"]
            project_name = project.get("name_with_namespace", project.get("name", "Unknown"))
            
            # Get recent merge requests in this project
            merge_requests = await fetch_json(
                session,
                f"{BASE_URL}/projects/{project_id}/merge_requests",
                params={"state": "all", "per_page": 50, "order_by": "updated_at"}
            )
            
            if merge_requests:
                for mr in merge_requests:
                    try:
                        mr_iid = mr["iid"]
                        
                        # Get MR notes/comments
                        notes = await fetch_json(
                            session,
                            f"{BASE_URL}/projects/{project_id}/merge_requests/{mr_iid}/notes",
                            params={"per_page": 50}
                        )
                        
                        if notes:
                            # Filter comments by the specific user and exclude system notes
                            for note in notes:
                                if (note.get("author", {}).get("id") == user_id and 
                                    not note.get("system", False)):
                                    note["mr_title"] = mr["title"]
                                    note["mr_url"] = mr.get("web_url", "")
                                    note["project_name"] = project_name
                                    user_comments.append(note)
                    except Exception:
                        continue
        except Exception:
            continue
    
    save_to_cache(cache_key, user_comments)
    return user_comments

async def fetch_issue_comments_by_user(session, user_id, projects):
    """Fetch ALL comments made by user on issues across accessible projects"""
    cache_key = get_cache_key(f"issue_comments_{user_id}", "")
    cached_comments = get_from_cache(cache_key)
    
    if cached_comments is not None:
        return cached_comments
    
    user_comments = []
    
    # Limit to first 20 projects for performance
    limited_projects = projects[:20] if len(projects) > 20 else projects
    
    for project in limited_projects:
        try:
            project_id = project["id"]
            project_name = project.get("name_with_namespace", project.get("name", "Unknown"))
            
            # Get recent issues in this project
            issues = await fetch_json(
                session,
                f"{BASE_URL}/projects/{project_id}/issues",
                params={"state": "all", "per_page": 50, "order_by": "updated_at"}
            )
            
            if issues:
                for issue in issues:
                    try:
                        issue_iid = issue["iid"]
                        
                        # Get issue notes/comments
                        notes = await fetch_json(
                            session,
                            f"{BASE_URL}/projects/{project_id}/issues/{issue_iid}/notes",
                            params={"per_page": 50}
                        )
                        
                        if notes:
                            # Filter comments by the specific user and exclude system notes
                            for note in notes:
                                if (note.get("author", {}).get("id") == user_id and 
                                    not note.get("system", False)):
                                    note["issue_title"] = issue["title"]
                                    note["issue_url"] = issue.get("web_url", "")
                                    note["project_name"] = project_name
                                    user_comments.append(note)
                    except Exception:
                        continue
        except Exception:
            continue
    
    save_to_cache(cache_key, user_comments)
    return user_comments

# --- MAIN GATHER FUNCTION ---
async def gather_data(username):
    async with aiohttp.ClientSession() as session:
        # Fetch user information
        user = await fetch_user(session, username)
        if not user:
            raise ValueError("User not found!")
        
        user_id = user["id"]
        user_email = user.get("public_email") or user.get("email", "")
        user_name = user.get("name", "")
        username = user["username"]  # Use the actual username from GitLab
        
        st.info(f"🔍 Found user: {user_name} (@{username}) [ID: {user_id}]")
        st.info(f"📧 Email: {user_email or 'Not available'}")
        
        # Fetch projects - get both owned and contributed, plus all accessible
        owned_projects = await fetch_projects(session, user_id)
        contributed_projects = await fetch_contributed_projects(session, user_id)
        all_accessible_projects = await fetch_all_accessible_projects(session)
        
        # Combine all projects and deduplicate
        all_projects = {}
        for proj in owned_projects + contributed_projects + all_accessible_projects:
            all_projects[proj["id"]] = proj
        projects = list(all_projects.values())
        
        # Limit projects for better performance
        if len(projects) > 50:
            st.warning(f"⚠️ Found {len(projects)} projects. Limiting to first 50 for performance.")
            projects = projects[:50]
        
        st.info(f"📁 Scanning {len(projects)} total projects ({len(owned_projects)} owned, {len(contributed_projects)} contributed)")
        
        # Fetch commits for each project with progress tracking
        commits_by_project = {}
        total_commits = 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, project in enumerate(projects):
            project_id = project["id"]
            project_name = project.get("name_with_namespace", project.get("name", "Unknown"))
            
            status_text.text(f"Processing commits in: {project_name[:50]}...")
            
            commits = await fetch_commits_by_author(
                session, project_id, user_id, username, user_email, user_name, project_name
            )
            
            if commits:
                commits_by_project[project_name] = commits
                total_commits += len(commits)
            
            progress_bar.progress((i + 1) / len(projects))
        
        progress_bar.empty()
        status_text.empty()
        st.success(f"📝 Found {total_commits} total commits across {len(commits_by_project)} projects")
        
        # Fetch MRs authored by user
        status_text.text("Fetching merge requests...")
        merge_requests = await fetch_merge_requests_by_author(session, user_id)
        st.info(f"🔀 Found {len(merge_requests)} merge requests authored by user")
        
        # Fetch Issues authored by user
        status_text.text("Fetching issues...")
        issues = await fetch_issues_by_author(session, user_id)
        st.info(f"🐛 Found {len(issues)} issues created by user")
        
        # Fetch ALL comments made by user across all projects
        status_text.text("Fetching MR comments...")
        mr_comments = await fetch_mr_comments_by_user(session, user_id, projects)
        
        status_text.text("Fetching issue comments...")
        issue_comments = await fetch_issue_comments_by_user(session, user_id, projects)
        
        status_text.empty()
        st.success(f"💬 Found {len(mr_comments)} MR comments, {len(issue_comments)} issue comments")
        
        return user, projects, commits_by_project, merge_requests, issues, mr_comments, issue_comments

def calculate_contribution_stats(commits_by_project, merge_requests, issues, mr_comments, issue_comments):
    """Calculate comprehensive contribution statistics"""
    total_commits = sum(len(commits) for commits in commits_by_project.values())
    total_mrs = len(merge_requests)
    total_issues = len(issues)
    total_mr_comments = len(mr_comments)
    total_issue_comments = len(issue_comments)
    total_contributions = total_commits + total_mrs + total_issues + total_mr_comments + total_issue_comments
    
    return {
        "total_commits": total_commits,
        "total_mrs": total_mrs,
        "total_issues": total_issues,
        "total_mr_comments": total_mr_comments,
        "total_issue_comments": total_issue_comments,
        "total_contributions": total_contributions
    }

def format_commit_message(message):
    """Format commit message to show type and scope"""
    # Common commit prefixes
    patterns = {
        r'^feat(\(.+\))?:': '🆕 Feature',
        r'^fix(\(.+\))?:': '🐛 Fix',
        r'^docs(\(.+\))?:': '📚 Docs',
        r'^style(\(.+\))?:': '💄 Style',
        r'^refactor(\(.+\))?:': '♻️ Refactor',
        r'^test(\(.+\))?:': '🧪 Test',
        r'^chore(\(.+\))?:': '🔧 Chore',
        r'^perf(\(.+\))?:': '⚡ Performance',
        r'^ci(\(.+\))?:': '👷 CI',
        r'^build(\(.+\))?:': '📦 Build',
    }
    
    for pattern, emoji_type in patterns.items():
        if re.match(pattern, message, re.IGNORECASE):
            return f"{emoji_type} | {message}"
    
    return f"📝 Commit | {message}"

# --- STREAMLIT UI ---
st.set_page_config(page_title="GitLab Contribution Dashboard", page_icon="📊", layout="wide")

st.title("📊 GitLab Contribution Dashboard")
st.markdown("**Comprehensive tracking of commits, issues, MRs, and comments by a specific author across all accessible projects**")

# Add control buttons in the top area
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    st.markdown("---")
with col2:
    if st.button("🔄 Clear Cache", help="Clear cached data to fetch fresh information"):
        clear_cache()
        st.success("✅ Cache cleared!")
        st.rerun()
with col3:
    if st.button("🗑️ Reset All", help="Reset all data and start fresh"):
        reset_all_data()
        st.success("✅ All data reset!")
        st.rerun()

username = st.text_input("🔍 Enter GitLab Username", value=st.session_state.last_username, placeholder="e.g., john.doe")

# Show cache status
if st.session_state.cache:
    cache_info = f"💾 Cache: {len(st.session_state.cache)} items stored"
    oldest_cache = min(st.session_state.cache_timestamps.values()) if st.session_state.cache_timestamps else datetime.now()
    cache_age = (datetime.now() - oldest_cache).seconds // 60
    if cache_age < 60:
        cache_info += f" (oldest: {cache_age}m ago)"
    else:
        cache_info += f" (oldest: {cache_age//60}h {cache_age%60}m ago)"
    st.caption(cache_info)

need_fetch = username and (
    username != st.session_state.last_username or st.session_state.user_data is None
)

if username and need_fetch:
    with st.spinner("🔄 Fetching comprehensive GitLab data (this may take a while)..."):
        try:
            user, projects, commits_by_project, merge_requests, issues, mr_comments, issue_comments = asyncio.run(
                gather_data(username)
            )
            st.session_state.user_data = user
            st.session_state.projects_data = projects
            st.session_state.commits_data = commits_by_project
            st.session_state.merge_requests_data = merge_requests
            st.session_state.issues_data = issues
            st.session_state.mr_comments_data = mr_comments
            st.session_state.issue_comments_data = issue_comments
            st.session_state.last_username = username
            st.success("✅ Data fetched successfully!")
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.error("Please check your GitLab token, permissions, and base URL.")

if username and st.session_state.user_data:
    user = st.session_state.user_data
    projects = st.session_state.projects_data
    commits_by_project = st.session_state.commits_data
    merge_requests = st.session_state.merge_requests_data
    issues = st.session_state.issues_data
    mr_comments = st.session_state.mr_comments_data
    issue_comments = st.session_state.issue_comments_data
    
    # Calculate stats
    stats = calculate_contribution_stats(commits_by_project, merge_requests, issues, mr_comments, issue_comments)
    
    # User Profile Section
    col1, col2 = st.columns([1, 2])
    with col1:
        if user.get('avatar_url'):
            st.image(user.get('avatar_url', ''), width=150)
    with col2:
        st.subheader(f"👤 {user['name']} (@{user['username']})")
        st.write(f"📧 **Email:** {user.get('public_email', 'Not public')}")
        
        # Handle member since date safely
        try:
            if user.get('created_at'):
                member_since = parser.parse(user['created_at']).strftime('%B %Y')
                st.write(f"📅 **Member since:** {member_since}")
        except:
            pass
            
        if user.get('bio'):
            st.write(f"📝 **Bio:** {user['bio']}")
        
        # Add profile link
        if user.get('web_url'):
            st.markdown(f"🔗 **Profile:** [{user['web_url']}]({user['web_url']})")
    
    st.markdown("---")
    
    # Statistics Overview
    st.subheader("📈 Contribution Statistics")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        st.metric("📝 Total Commits", stats["total_commits"])
    with col2:
        st.metric("🔀 Merge Requests", stats["total_mrs"])
    with col3:
        st.metric("🐛 Issues Created", stats["total_issues"])
    with col4:
        st.metric("💬 MR Comments", stats["total_mr_comments"])
    with col5:
        st.metric("💭 Issue Comments", stats["total_issue_comments"])
    with col6:
        st.metric("🎯 Total Contributions", stats["total_contributions"])
    
    st.markdown("---")
    
    # Filters
    st.subheader("🔧 Filters")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        show_commits = st.checkbox("📝 Show Commits", value=True)
        show_mrs = st.checkbox("🔀 Show Merge Requests", value=True)
    with col2:
        show_issues = st.checkbox("🐛 Show Issues", value=True)
        show_comments = st.checkbox("💬 Show Comments", value=True)
    with col3:
        project_names = list(commits_by_project.keys()) if commits_by_project else []
        selected_project = st.selectbox("📁 Filter by Project", ["All Projects"] + project_names)
    
    # Date range filter
    min_date, max_date = datetime(2020, 1, 1), datetime.now()
    date_range = st.date_input("📅 Filter by Date Range", [min_date.date(), max_date.date()])
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range[0] if date_range else min_date.date()
    
    st.markdown("---")
    
    # Commits Section
    if show_commits and commits_by_project:
        st.subheader("📝 Commits by Author")
        
        for project_name, commits in commits_by_project.items():
            if selected_project != "All Projects" and project_name != selected_project:
                continue
            if not commits:
                continue
            
            # Filter by date
            filtered = []
            for commit in commits:
                try:
                    if commit.get("created_at"):
                        commit_date = parser.parse(commit["created_at"]).date()
                        if start_date <= commit_date <= end_date:
                            filtered.append(commit)
                except Exception:
                    continue
            
            if not filtered:
                continue
            
            with st.expander(f"📁 {project_name} ({len(filtered)} commits)", expanded=len(commits_by_project) <= 3):
                data = []
                for i, c in enumerate(filtered, start=1):
                    try:
                        commit_date = parser.parse(c["created_at"]).strftime("%Y-%m-%d %H:%M") if c.get("created_at") else "Unknown"
                        commit_link = c.get("web_url", "#")
                        formatted_message = format_commit_message(c.get("title", "No message"))
                        
                        data.append({
                            "#": i,
                            "Type & Message": formatted_message[:80] + "..." if len(formatted_message) > 80 else formatted_message,
                            "Author": c.get("author_name", "Unknown"),
                            "Author Email": c.get("author_email", "Unknown"),
                            "Date": commit_date,
                            "SHA": c.get("short_id", c.get("id", "")[:8]),
                            "Link": f'<a href="{commit_link}" target="_blank">🔗 View</a>' if commit_link != "#" else "No link"
                        })
                    except Exception:
                        continue
                
                if data:
                    df = pd.DataFrame(data)
                    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
    
    # Continue from where the code was cut off - Merge Requests Section

    # Merge Requests Section
    if show_mrs and merge_requests:
        st.subheader("🔀 Merge Requests by Author")
        
        # Filter merge requests by date
        filtered_mrs = []
        for mr in merge_requests:
            if selected_project != "All Projects":
                # Check if MR belongs to selected project
                mr_project = mr.get("project_id")
                selected_proj_obj = next((p for p in projects if p.get("name_with_namespace", p.get("name")) == selected_project), None)
                if not selected_proj_obj or mr_project != selected_proj_obj.get("id"):
                    continue
            
            try:
                if mr.get("created_at"):
                    mr_date = parser.parse(mr["created_at"]).date()
                    if start_date <= mr_date <= end_date:
                        filtered_mrs.append(mr)
            except Exception:
                continue
        
        if filtered_mrs:
            with st.expander(f"🔀 Merge Requests ({len(filtered_mrs)} total)", expanded=True):
                data = []
                for i, mr in enumerate(filtered_mrs, start=1):
                    try:
                        created_date = parser.parse(mr["created_at"]).strftime("%Y-%m-%d %H:%M") if mr.get("created_at") else "Unknown"
                        mr_link = mr.get("web_url", "#")
                        state = mr.get("state", "unknown").upper()
                        state_emoji = {"OPENED": "🟢", "CLOSED": "🔴", "MERGED": "✅"}.get(state, "⚪")
                        
                        # Get project name
                        project_name = "Unknown Project"
                        if mr.get("project_id"):
                            proj = next((p for p in projects if p["id"] == mr["project_id"]), None)
                            if proj:
                                project_name = proj.get("name_with_namespace", proj.get("name", "Unknown"))
                        
                        data.append({
                            "#": i,
                            "Title": mr.get("title", "No title")[:60] + "..." if len(mr.get("title", "")) > 60 else mr.get("title", "No title"),
                            "Project": project_name,
                            "State": f"{state_emoji} {state}",
                            "Target Branch": mr.get("target_branch", "Unknown"),
                            "Source Branch": mr.get("source_branch", "Unknown"),
                            "Created": created_date,
                            "Link": f'<a href="{mr_link}" target="_blank">🔗 View MR</a>' if mr_link != "#" else "No link"
                        })
                    except Exception:
                        continue
                
                if data:
                    df = pd.DataFrame(data)
                    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.info("No merge requests found for the selected filters.")
    
    # Issues Section
    if show_issues and issues:
        st.subheader("🐛 Issues Created by Author")
        
        # Filter issues by date
        filtered_issues = []
        for issue in issues:
            if selected_project != "All Projects":
                # Check if issue belongs to selected project
                issue_project = issue.get("project_id")
                selected_proj_obj = next((p for p in projects if p.get("name_with_namespace", p.get("name")) == selected_project), None)
                if not selected_proj_obj or issue_project != selected_proj_obj.get("id"):
                    continue
            
            try:
                if issue.get("created_at"):
                    issue_date = parser.parse(issue["created_at"]).date()
                    if start_date <= issue_date <= end_date:
                        filtered_issues.append(issue)
            except Exception:
                continue
        
        if filtered_issues:
            with st.expander(f"🐛 Issues ({len(filtered_issues)} total)", expanded=True):
                data = []
                for i, issue in enumerate(filtered_issues, start=1):
                    try:
                        created_date = parser.parse(issue["created_at"]).strftime("%Y-%m-%d %H:%M") if issue.get("created_at") else "Unknown"
                        issue_link = issue.get("web_url", "#")
                        state = issue.get("state", "unknown").upper()
                        state_emoji = {"OPENED": "🟢", "CLOSED": "🔴"}.get(state, "⚪")
                        
                        # Get project name
                        project_name = "Unknown Project"
                        if issue.get("project_id"):
                            proj = next((p for p in projects if p["id"] == issue["project_id"]), None)
                            if proj:
                                project_name = proj.get("name_with_namespace", proj.get("name", "Unknown"))
                        
                        # Get labels
                        labels = issue.get("labels", [])
                        labels_str = ", ".join(labels[:3]) + ("..." if len(labels) > 3 else "") if labels else "No labels"
                        
                        data.append({
                            "#": i,
                            "Title": issue.get("title", "No title")[:60] + "..." if len(issue.get("title", "")) > 60 else issue.get("title", "No title"),
                            "Project": project_name,
                            "State": f"{state_emoji} {state}",
                            "Labels": labels_str,
                            "Created": created_date,
                            "Link": f'<a href="{issue_link}" target="_blank">🔗 View Issue</a>' if issue_link != "#" else "No link"
                        })
                    except Exception:
                        continue
                
                if data:
                    df = pd.DataFrame(data)
                    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.info("No issues found for the selected filters.")
    
    # Comments Section
    if show_comments and (mr_comments or issue_comments):
        st.subheader("💬 Comments by Author")
        
        # Filter comments by date and project
        def filter_comments(comments, comment_type):
            filtered = []
            for comment in comments:
                if selected_project != "All Projects":
                    comment_project = comment.get("project_name", "")
                    if comment_project != selected_project:
                        continue
                
                try:
                    if comment.get("created_at"):
                        comment_date = parser.parse(comment["created_at"]).date()
                        if start_date <= comment_date <= end_date:
                            filtered.append(comment)
                except Exception:
                    continue
            return filtered
        
        filtered_mr_comments = filter_comments(mr_comments, "MR")
        filtered_issue_comments = filter_comments(issue_comments, "Issue")
        
        # MR Comments
        if filtered_mr_comments:
            with st.expander(f"💬 Merge Request Comments ({len(filtered_mr_comments)} total)", expanded=False):
                data = []
                for i, comment in enumerate(filtered_mr_comments, start=1):
                    try:
                        created_date = parser.parse(comment["created_at"]).strftime("%Y-%m-%d %H:%M") if comment.get("created_at") else "Unknown"
                        comment_url = comment.get("mr_url", "#")
                        comment_body = comment.get("body", "No content")
                        # Truncate long comments
                        if len(comment_body) > 100:
                            comment_body = comment_body[:100] + "..."
                        
                        data.append({
                            "#": i,
                            "MR Title": comment.get("mr_title", "Unknown")[:50] + "..." if len(comment.get("mr_title", "")) > 50 else comment.get("mr_title", "Unknown"),
                            "Project": comment.get("project_name", "Unknown"),
                            "Comment": comment_body,
                            "Created": created_date,
                            "Link": f'<a href="{comment_url}" target="_blank">🔗 View MR</a>' if comment_url != "#" else "No link"
                        })
                    except Exception:
                        continue
                
                if data:
                    df = pd.DataFrame(data)
                    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        
        # Issue Comments
        if filtered_issue_comments:
            with st.expander(f"💭 Issue Comments ({len(filtered_issue_comments)} total)", expanded=False):
                data = []
                for i, comment in enumerate(filtered_issue_comments, start=1):
                    try:
                        created_date = parser.parse(comment["created_at"]).strftime("%Y-%m-%d %H:%M") if comment.get("created_at") else "Unknown"
                        comment_url = comment.get("issue_url", "#")
                        comment_body = comment.get("body", "No content")
                        # Truncate long comments
                        if len(comment_body) > 100:
                            comment_body = comment_body[:100] + "..."
                        
                        data.append({
                            "#": i,
                            "Issue Title": comment.get("issue_title", "Unknown")[:50] + "..." if len(comment.get("issue_title", "")) > 50 else comment.get("issue_title", "Unknown"),
                            "Project": comment.get("project_name", "Unknown"),
                            "Comment": comment_body,
                            "Created": created_date,
                            "Link": f'<a href="{comment_url}" target="_blank">🔗 View Issue</a>' if comment_url != "#" else "No link"
                        })
                    except Exception:
                        continue
                
                if data:
                    df = pd.DataFrame(data)
                    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        
        if not filtered_mr_comments and not filtered_issue_comments:
            st.info("No comments found for the selected filters.")
    
    # Activity Timeline
    st.markdown("---")
    st.subheader("📅 Activity Timeline")
    
    # Collect all activities with dates
    all_activities = []
    
    # Add commits
    if commits_by_project:
        for project_name, commits in commits_by_project.items():
            if selected_project != "All Projects" and project_name != selected_project:
                continue
            for commit in commits:
                try:
                    if commit.get("created_at"):
                        commit_date = parser.parse(commit["created_at"])
                        if start_date <= commit_date.date() <= end_date:
                            all_activities.append({
                                "date": commit_date,
                                "type": "📝 Commit",
                                "project": project_name,
                                "title": commit.get("title", "No message")[:50] + "..." if len(commit.get("title", "")) > 50 else commit.get("title", "No message"),
                                "url": commit.get("web_url", "#")
                            })
                except Exception:
                    continue
    
    # Add merge requests
    if merge_requests:
        for mr in merge_requests:
            if selected_project != "All Projects":
                mr_project = mr.get("project_id")
                selected_proj_obj = next((p for p in projects if p.get("name_with_namespace", p.get("name")) == selected_project), None)
                if not selected_proj_obj or mr_project != selected_proj_obj.get("id"):
                    continue
            
            try:
                if mr.get("created_at"):
                    mr_date = parser.parse(mr["created_at"])
                    if start_date <= mr_date.date() <= end_date:
                        project_name = "Unknown Project"
                        if mr.get("project_id"):
                            proj = next((p for p in projects if p["id"] == mr["project_id"]), None)
                            if proj:
                                project_name = proj.get("name_with_namespace", proj.get("name", "Unknown"))
                        
                        all_activities.append({
                            "date": mr_date,
                            "type": "🔀 Merge Request",
                            "project": project_name,
                            "title": mr.get("title", "No title")[:50] + "..." if len(mr.get("title", "")) > 50 else mr.get("title", "No title"),
                            "url": mr.get("web_url", "#")
                        })
            except Exception:
                continue
    
    # Add issues
    if issues:
        for issue in issues:
            if selected_project != "All Projects":
                issue_project = issue.get("project_id")
                selected_proj_obj = next((p for p in projects if p.get("name_with_namespace", p.get("name")) == selected_project), None)
                if not selected_proj_obj or issue_project != selected_proj_obj.get("id"):
                    continue
            
            try:
                if issue.get("created_at"):
                    issue_date = parser.parse(issue["created_at"])
                    if start_date <= issue_date.date() <= end_date:
                        project_name = "Unknown Project"
                        if issue.get("project_id"):
                            proj = next((p for p in projects if p["id"] == issue["project_id"]), None)
                            if proj:
                                project_name = proj.get("name_with_namespace", proj.get("name", "Unknown"))
                        
                        all_activities.append({
                            "date": issue_date,
                            "type": "🐛 Issue",
                            "project": project_name,
                            "title": issue.get("title", "No title")[:50] + "..." if len(issue.get("title", "")) > 50 else issue.get("title", "No title"),
                            "url": issue.get("web_url", "#")
                        })
            except Exception:
                continue
    
    # Sort activities by date (most recent first)
    all_activities.sort(key=lambda x: x["date"], reverse=True)
    
    if all_activities:
        # Limit to most recent 50 activities for performance
        display_activities = all_activities[:50]
        
        with st.expander(f"📅 Recent Activity ({len(display_activities)} of {len(all_activities)} total)", expanded=False):
            data = []
            for i, activity in enumerate(display_activities, start=1):
                try:
                    formatted_date = activity["date"].strftime("%Y-%m-%d %H:%M")
                    data.append({
                        "#": i,
                        "Date": formatted_date,
                        "Type": activity["type"],
                        "Project": activity["project"],
                        "Title": activity["title"],
                        "Link": f'<a href="{activity["url"]}" target="_blank">🔗 View</a>' if activity["url"] != "#" else "No link"
                    })
                except Exception:
                    continue
            
            if data:
                df = pd.DataFrame(data)
                st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("No activities found for the selected filters.")
    
    # Export functionality
    st.markdown("---")
    st.subheader("📥 Export Data")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📊 Export to CSV"):
            # Prepare data for export
            export_data = []
            
            # Add commits
            if commits_by_project:
                for project_name, commits in commits_by_project.items():
                    for commit in commits:
                        try:
                            export_data.append({
                                "Type": "Commit",
                                "Project": project_name,
                                "Title": commit.get("title", ""),
                                "Author": commit.get("author_name", ""),
                                "Date": commit.get("created_at", ""),
                                "URL": commit.get("web_url", "")
                            })
                        except Exception:
                            continue
            
            # Add merge requests
            for mr in merge_requests:
                try:
                    project_name = "Unknown Project"
                    if mr.get("project_id"):
                        proj = next((p for p in projects if p["id"] == mr["project_id"]), None)
                        if proj:
                            project_name = proj.get("name_with_namespace", proj.get("name", "Unknown"))
                    
                    export_data.append({
                        "Type": "Merge Request",
                        "Project": project_name,
                        "Title": mr.get("title", ""),
                        "Author": mr.get("author", {}).get("name", ""),
                        "Date": mr.get("created_at", ""),
                        "URL": mr.get("web_url", "")
                    })
                except Exception:
                    continue
            
            # Add issues
            for issue in issues:
                try:
                    project_name = "Unknown Project"
                    if issue.get("project_id"):
                        proj = next((p for p in projects if p["id"] == issue["project_id"]), None)
                        if proj:
                            project_name = proj.get("name_with_namespace", proj.get("name", "Unknown"))
                    
                    export_data.append({
                        "Type": "Issue",
                        "Project": project_name,
                        "Title": issue.get("title", ""),
                        "Author": issue.get("author", {}).get("name", ""),
                        "Date": issue.get("created_at", ""),
                        "URL": issue.get("web_url", "")
                    })
                except Exception:
                    continue
            
            if export_data:
                df_export = pd.DataFrame(export_data)
                csv = df_export.to_csv(index=False)
                st.download_button(
                    label="📥 Download CSV",
                    data=csv,
                    file_name=f"gitlab_contributions_{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            else:
                st.warning("No data to export!")
    
    with col2:
        if st.button("📋 Copy Summary to Clipboard"):
            summary = f"""GitLab Contribution Summary for {user['name']} (@{user['username']})
            
📊 Statistics:
- Total Commits: {stats['total_commits']}
- Merge Requests: {stats['total_mrs']}
- Issues Created: {stats['total_issues']}
- MR Comments: {stats['total_mr_comments']}
- Issue Comments: {stats['total_issue_comments']}
- Total Contributions: {stats['total_contributions']}

📁 Projects Involved: {len(projects)}
📅 Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            st.code(summary)
            st.info("📋 Summary ready! Copy the text above.")

else:
    if not username:
        st.info("👆 Please enter a GitLab username to get started.")
    else:
        st.info("🔄 Click the search button or press Enter to fetch data.")

# Footer
st.markdown("---")
st.markdown("Built with ❤️ using Streamlit | GitLab API Integration")
st.caption("💡 **Tip:** Use the cache system to avoid re-fetching data. Clear cache if you need fresh information.")