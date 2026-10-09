> **Historical note — written 2026-03-13, still accurate.** This is the original build
> log of the dashboard's settings tabs. Checked against `src/zyg_dashboard` on
> 2026-10-05: every script it names
> (`static/js/dashboard_tab_{users,error_logs,job_status,monitoring_ui,api_authorization}.js`,
> `dashboard_tabs.js`, `dashboard_theme.js`, `dashboard_settings_{buttons,backgrounds}.js`),
> every route (`/api/dashboard/{users,users/avatar/<id>,error_logs,job_status,monitoring_jobs,themes/config}`)
> and `dashboard_config.py` still exist. Two things have moved on: the dashboard now has
> far more tabs than the five described here, and the Windows `C:\...\Layouts and Themes`
> paths are resolved relative to the package. Read it as history, not as the current
> tab inventory.

# CrewAI Dashboard – Implementation Steps (Completed)

## 1. Tab list on the left
- Added left sidebar with tabs: **Users**, **Error Logs**, **Job Status**, **Monitoring UI**, **Api Authorization**.
- Sidebar is fixed; main content area shows the active tab panel.
- Tab switching and panel visibility handled in `static/js/dashboard_tabs.js`.

## 2. Users tab (new script: `static/js/dashboard_tab_users.js`)
- Three columns: **Users** | **Permissions** | **Login Credentials**.
- Rows: Admins (Full control, Password), Operators (Create Tasks, Create Schedules., ID + Password), Ai Operators (same), Spectators (View only, None).
- “Edit” under each row; clicking a row opens the role detail view.
- Role detail: empty ring with faceless placeholder and “+” to add user.
- Add-user form: Name, Id, Password, Re-enter Password, E-mail (Optional), **Add** button; data saved via `/api/dashboard/users`.
- After add: new user shown as ring with name below; small “+” inside ring to upload picture; avatar saved via `/api/dashboard/users/avatar/<user_id>` and `avatar_url` stored in user list for persistence.
- Same behavior for Admins, Operators, Ai Operators, Spectators (role id drives which list is edited).

## 3. Error Logs tab (new script: `static/js/dashboard_tab_error_logs.js`)
- Circular progress bars for: **AI model fails**, **GPU memory overflows**, **Timeouts**, **API errors** (each backed by API data).
- Space between API errors and **Test System** (placeholder only).
- Clicking a circular bar opens a dialog listing all entries for that category.
- Data from `/api/dashboard/error_logs`; persisted in `dashboard_error_logs.json`.

## 4. Job Status tab (new script: `static/js/dashboard_tab_job_status.js`)
- Four circular progress bars showing **numbers**: Running, Completed, Failed, Retried.
- Labels under bars: Running, Completed, Failed, Retried.
- Clicking a bar opens a dialog with the list for that status.
- Data from `/api/dashboard/job_status`; persisted in `dashboard_job_status.json`.

## 5. Monitoring UI tab (new script: `static/js/dashboard_tab_monitoring_ui.js`)
- Two buttons at top: **Active Jobs** (default) / **Finished Jobs**.
- List columns: start time, end time, duration, error message (if any), Job Description.
- Data from `/api/dashboard/monitoring_jobs`; persisted in `dashboard_monitoring_jobs.json`.

## 6. Api Authorization tab (new script: `static/js/dashboard_tab_api_authorization.js`)
- New script; placeholder UI for API authorization (content to be implemented later).

## 7. Settings icon (top right)
- Click opens menu: **Buttons**, **Backgrounds**.

## 8. Buttons settings (new script: `static/js/dashboard_settings_buttons.js`)
- List of button themes loaded from `C:\...\Layouts and Themes\Buttons` (HTML files).
- Preview iframe for selected button.
- **Apply** at bottom; on click, popup with checkboxes for tabs and **Apply To All** (select all).
- Second **Apply** in popup applies selection and saves to theme config; button style applied to buttons in selected tabs.
- Persistence: `dashboard_theme_config.json` and `/api/dashboard/themes/config`.

## 9. Backgrounds settings (new script: `static/js/dashboard_settings_backgrounds.js`)
- Same pattern as Buttons; list from `C:\...\Layouts and Themes\Background`.
- Preview, Apply, Apply To All + tab checkboxes, Apply to confirm; separate persistent storage in same theme config.

## 10. Default theme and persistence
- Default: **Smoky Pearl** (background) and **Scaled 18 Subtle** (buttons), as in Layouts and Themes HTML.
- Theme applied on load via `static/js/dashboard_theme.js`; config read from `/api/dashboard/themes/config`.
- `dashboard_theme_config.json` holds `button_theme`, `background_theme`, `apply_buttons_to_tabs`, `apply_background_to_tabs` for fast reload.

## 11. Backend (Flask in `crewai_web_gui.py`)
- `dashboard_config.py`: paths for Layouts and Themes, dashboard JSON files, avatars dir.
- Routes: theme config GET/POST, buttons list + file serve, backgrounds list + file serve, users GET/POST, avatar upload, error_logs GET/POST, job_status GET/POST, monitoring_jobs GET/POST.
- Data files: `dashboard_theme_config.json`, `dashboard_users.json`, `dashboard_error_logs.json`, `dashboard_job_status.json`, `dashboard_monitoring_jobs.json`; avatars under `static/avatars/` (created on first upload).

## 12. Modularization
- One script per tab: `dashboard_tab_users.js`, `dashboard_tab_error_logs.js`, `dashboard_tab_job_status.js`, `dashboard_tab_monitoring_ui.js`, `dashboard_tab_api_authorization.js`.
- Shared: `dashboard_tabs.js` (routing), `dashboard_theme.js` (theme apply), `dashboard_settings_buttons.js`, `dashboard_settings_backgrounds.js`.
- Backend: `dashboard_config.py`; dashboard routes and helpers in `crewai_web_gui.py`.

All steps above have been implemented.
