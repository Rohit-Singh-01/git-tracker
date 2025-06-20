# GitLab Personal + Contribution Tracker

A simple and efficient **Streamlit-based application** to track and analyze **GitLab user contributions**, designed for educational institutions and individual developers to monitor coding activity through intuitive dashboards.

## 🚀 Features

### Individual Tracking (`app.py`)
- **Personal Dashboard**: View a single user's GitLab contributions  
- **Real-time Data Fetching**: Async API calls for fast data retrieval  
- **Contribution Metrics**:
  - Total commits authored  
  - Merge Requests created (with state: open/closed/reopened)  
  - Issues opened (with state: open/closed/reopened)  
  - Comments on MRs and issues  
- **Date Range Filtering**: Analyze contributions within specific time frames  
- **Project Overview**: See personal and contributed projects  
- **Session Persistence**: Maintain data during the session  

### Bulk Summary Tracker (`bulk_summary.py`)
- Track multiple GitLab users at once using CSV or manual input  
- View summary metrics including:
  - Total commits  
  - Merge requests with current status  
  - Issues with current status  
  - Comment count  
- Includes caching, error handling, and real-time status updates per user  
- Responsive and memory-efficient with time-based analytics  

### Individual Detailed View (`detailed_view.py`)
- Deep dive into a single user’s GitLab activity  
- Filterable views of:
  - Commits per project  
  - Issue history with state changes  
  - MR history with current status  
- Export charts and filtered data as PDF  
- User-friendly UI with responsive design  

### Bulk Student Progress Tracking (`progress_view.py`)
- **CSV Upload**: Upload student usernames via CSV file  
- **Progress Metrics**:
  - Commit count  
  - Issue creation and closure rate  
  - MR creation and resolution status  
- **Performance Comparison**: Compare students based on tracked activity  
- **Data Caching**: Smart caching to improve performance  
- **Export Functionality**: Download results as CSV files  
- **Filter & Sort**: Apply filters by date, username, or project  

## 📊 Metrics Tracked

### Core Contribution Metrics
| Metric             | Description |
|--------------------|-------------|
| **Commits**        | Total commits authored |
| **Merge Requests** | Created MRs, grouped by state (open/closed/reopened) |
| **Issues**         | Opened issues, with current state (open/closed/reopened) |
| **MR Comments**    | Number of comments made on merge requests |
| **Issue Comments** | Number of comments made on issues |
| **Total Contributions** | Sum of above metrics |

### Project Metrics
- **Personal Projects**: Projects owned by the user  
- **Contributed Projects**: Projects the user has contributed to  

## 🔧 Technical Architecture

### API Integration
The app uses GitLab’s REST API v4 endpoints to fetch real-time contribution data.

#### User Information
```
GET /api/v4/users?username={username}
```

#### Project Data
```
GET /api/v4/users/{user_id}/projects
GET /api/v4/users/{user_id}/contributed_projects?per_page=100
```

#### Contribution Data
```
GET /api/v4/projects/{project_id}/repository/commits?author_email={email}
GET /api/v4/projects/{project_id}/merge_requests?author_id={user_id}
GET /api/v4/projects/{project_id}/issues?author_id={user_id}&state=all
```

#### Comments and Notes
```
GET /api/v4/projects/{project_id}/issues/{issue_iid}/notes
GET /api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes
```

### Authentication
Uses GitLab **Personal Access Tokens** for secure access:
```python
headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
```

### Async Processing
Utilizes `aiohttp` for concurrent API calls:
```python
async def fetch_json(session, url, params=None):
    async with session.get(url, headers=headers, params=params) as response:
        response.raise_for_status()
        return await response.json()
```

## 🛠️ Setup & Installation

### Prerequisites
- Python 3.8+
- GitLab instance access
- GitLab Personal Access Token

### Dependencies
Install the required packages:
```bash
pip install streamlit aiohttp pandas numpy python-dateutil fpdf2 altair
```

### Configuration
Create a `.streamlit/secrets.toml` file:
```toml
[gitlab]
token = "your_gitlab_personal_access_token"
base_url = "https://your-gitlab-instance.com/api/v4"
```

### Running the App
```bash
# Clone the repo
git clone <your-repo-url>
cd gitlab-tracker

# Run the main app
streamlit run app.py

# For bulk progress tracking
streamlit run progress_view.py
```

## 📝 Usage

### Individual Tracking
1. Launch `app.py`  
2. Enter GitLab username  
3. Select date range  
4. View detailed contribution stats  

### Student Progress Tracking
1. Launch `progress_view.py`  
2. Prepare CSV with usernames  
3. Upload file and select date range  
4. View and export student activity reports  

### CSV Format
```csv
username,name
student1,John Doe
student2,Jane Smith
student3,Bob Johnson
```

## 🔄 Caching & Performance

- User data cached for 30 minutes  
- Full dataset cached for 1 hour  
- Efficient filtering and sorting logic  
- Async API calls for faster loading  

## 📤 Export Features

- Export filtered or full datasets as **CSV**
- Export includes:
  - Username
  - Commit count
  - MRs (with state: open/closed/reopened)
  - Issues (with state: open/closed/reopened)
  - Comment stats

## 🔐 Security Considerations

- GitLab tokens stored securely in `secrets.toml`  
- No persistent storage of user data  
- Each session is isolated from others  

## 🐛 Error Handling

- Graceful fallback for invalid users  
- Safe parsing of dates and API responses  
- Informative error messages for failed API calls  

## 📈 Use Cases

- Monitor student participation in GitLab-based courses
- Track developer activity across teams or semesters
- Generate progress reports based on real GitLab usage
- Evaluate contributions during internships or open-source programs