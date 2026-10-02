# BWU — University Academic Management System

A modern **University Academic Management System** frontend designed for managing academic workflows across students, faculty, and administrators.

> **Current Stage:** Frontend prototype  
> **Next Stage:** Backend + Database Integration  
> **Future Stage:** Motion Graphics & Advanced UI Interactions

---

## 📌 Overview

The **BWU Academic Management System** is a centralized academic platform designed around three major user roles:

- 🎓 **Student**
- 👨‍🏫 **Faculty**
- 🛡️ **Administrator**

The current project focuses on building a clean, responsive and modular frontend architecture. Each major management area is maintained as an independent HTML page, while the Admin Window provides a unified interface for accessing those modules.

---

## 👥 User Portals

### 🎓 Student Portal

Students can access their academic information through the Student Dashboard.

Current areas include:

- Dashboard
- Profile
- Courses
- Attendance
- Timetable
- Marks & Examinations
- Results
- Academic Records
- Logout

### 👨‍🏫 Faculty Portal

The Faculty Dashboard provides faculty members with tools related to their assigned academic responsibilities.

Current areas include:

- Dashboard
- Attendance Entry
- Class Information
- Syllabus Completion
- Academic Resource Upload
- Feedback Report
- Logout

### 🛡️ Admin Portal

The Administrator has a separate login and centralized Admin Window.

The Admin Window does **not** contain duplicated code from every management module. Instead, it works as a main navigation shell that loads the existing standalone modules by filename.

### Admin Modules

1. Admin Dashboard
2. Student Management
3. Faculty Management
4. Course Management
5. Faculty → Course Assignment
6. Class & Timetable Management
7. Attendance Overview
8. Marks & Examination
9. Syllabus Monitoring
10. Academic Resources
11. Reports
12. User & Access Control
13. System Settings

---

## 🗂️ Project Structure

```text
Academic-Management-System/
│
├── index.html
├── admin-login.html
├── admin-window.html
├── admin-dashboard.html
│
├── student-login.html
├── student-dashboard.html
│
├── faculty-login.html
├── faculty-dashboard.html
│
├── student-management.html
├── faculty-management.html
├── course-management.html
├── faculty-course-assignment.html
├── class-timetable-management.html
├── attendance-overview.html
├── marks-examination.html
├── syllabus-monitoring.html
├── academic-resources.html
├── reports.html
├── user-access-control.html
├── system-settings.html
│
├── style.css
├── script.js
│
└── README.md
```

---

## 🧩 Admin Architecture

```text
Admin Login
     │
     ▼
Admin Window
     │
     ├── Admin Dashboard
     ├── Student Management
     ├── Faculty Management
     ├── Course Management
     ├── Faculty → Course Assignment
     ├── Class & Timetable
     ├── Attendance
     ├── Marks & Examination
     ├── Syllabus Monitoring
     ├── Academic Resources
     ├── Reports
     ├── User & Access Control
     └── System Settings
```

The Admin Window connects to these pages using their filenames rather than copying their entire source code into one large HTML file.

This keeps the project:

- Modular
- Easier to maintain
- Easier to debug
- Easier to expand
- Less repetitive

---

## 🔐 Admin Login

The current frontend prototype contains a standalone Admin Login page.

### Demo credentials

```text
Administrator Code: BWU_ADMIN_001
Password: admin123
```

Successful login currently redirects to:

```text
admin-window.html
```

> The current authentication is frontend/demo authentication only. Real authentication will be implemented during backend integration.

---

## 📚 Academic Management Modules

### Student Management

Provides a centralized student directory with:

- Student code
- Department
- Batch
- Section
- Semester
- Status
- Academic profile

### Faculty Management

Provides faculty records including:

- Faculty code
- Department
- Designation
- Assigned batch
- Status
- Academic responsibilities

### Course Management

Manages:

- Course code
- Course name
- Credits
- Course type
- Semester
- Department
- Status

Course types include:

- Theory
- Lab / Practical
- Project
- Audit

### Faculty → Course Assignment

Structured assignment flow:

```text
Department
   ↓
Batch
   ↓
Section
   ↓
Semester
   ↓
Course
   ↓
Faculty
```

Additional assignment information includes:

- Class type
- Weekly hours
- Academic year

### Class & Timetable Management

Designed for:

- Classes
- Faculty
- Rooms
- Time slots
- Weekly schedules
- Breaks
- Academic groups

### Attendance Overview

Provides an administrative overview of:

- Overall attendance
- Classes held
- Classes attended
- Course-wise attendance
- Attendance status
- Monthly attendance trends

### Marks & Examination

Provides management of:

- Continuous assessments
- CT examinations
- Term-end examinations
- Marks
- Publication status
- Examination schedules
- Performance completion

### Syllabus Monitoring

Allows administrators to monitor:

- Planned topics
- Completed topics
- Pending topics
- Completion percentage
- Faculty responsibility
- Department-wise progress
- Delayed academic areas

### Academic Resources

Supports academic resource management for:

- PDF files
- DOCX files

Resources can be associated with:

- Department
- Batch
- Section
- Semester
- Course
- Faculty

### Reports

Designed for:

- Student Reports
- Faculty Reports
- Course Reports
- Attendance Reports
- Marks & Examination Reports
- Syllabus Reports
- Academic Resource Reports
- Timetable Reports
- Consolidated Academic Reports

Planned output formats:

```text
PDF
CSV
XLSX
```

### User & Access Control

Provides management of:

- User accounts
- User types
- Roles
- Access levels
- Account status
- Permissions
- Account locking
- Security activity

### System Settings

Provides centralized configuration for:

- Institution settings
- Academic settings
- Academic calendar
- Security
- Notifications
- Files & storage
- Preferences
- Audit logs

---

## 🎨 Design

The project follows a consistent visual design language:

- Clean modern interface
- Responsive layouts
- Professional academic UI
- Dark navy administration interface
- White content cards
- Blue / indigo accent colors
- Inter typography
- Font Awesome icons
- Modular page structure

The current version intentionally keeps motion effects limited so the core frontend functionality can be completed first.

---

## 💻 Technologies

### Current Frontend

- HTML5
- CSS3
- JavaScript
- Responsive Web Design
- Font Awesome
- Google Fonts

### Planned Backend

The backend technology and database architecture will be implemented in the next development phase.

The current frontend is structured so existing UI modules can later communicate with backend APIs instead of relying on static demo data.

---

## 🗄️ Planned Database Integration

Expected major entities include:

```text
Users
Students
Faculty
Departments
Courses
Faculty-Course Assignments
Classes
Timetables
Attendance
Examinations
Marks
Syllabus
Academic Resources
Reports
Roles
Permissions
System Settings
Audit Logs
```

The exact database schema will be finalized during backend development.

---

## 🔌 Backend Integration Plan

The project will gradually move from static frontend data to API-driven data.

```text
Frontend
   ↓
API
   ↓
Backend
   ↓
Database
```

Example:

```text
Student Login
     ↓
Authentication API
     ↓
Database
     ↓
Student Dashboard
```

Admin example:

```text
Admin
  ↓
Student Management
  ↓
API
  ↓
Student Database
  ↓
Create / Update / Delete / View
```

---

## ✨ Future Motion & Animation

Animations and motion graphics are intentionally postponed until the core frontend and backend structure is stable.

Planned enhancements may include:

- Sidebar transitions
- Dashboard card animations
- Page transitions
- Modal animations
- Loading states
- Skeleton loaders
- Animated charts
- Progress-bar transitions
- Button micro-interactions
- Toast notifications
- Login transitions
- Data-loading animations

Motion will be treated as a **UI enhancement layer**, separate from core business logic.

---

## 📱 Responsive Design

The interface is designed for:

- Desktop
- Laptop
- Tablet
- Mobile

Admin navigation also includes responsive behavior for smaller screens.

---

## 🚀 Running the Project

### Option 1 — Direct Browser

Open:

```text
index.html
```

in a browser.

### Option 2 — VS Code Live Server

Open the project folder in VS Code and launch `index.html` using Live Server.

### Option 3 — Local Development Server

A local development server can also be used when required.

---

## 🔗 Main Pages

| Page | Purpose |
|---|---|
| `index.html` | Main homepage |
| `student-login.html` | Student authentication |
| `student-dashboard.html` | Student workspace |
| `faculty-login.html` | Faculty authentication |
| `faculty-dashboard.html` | Faculty workspace |
| `admin-login.html` | Administrator authentication |
| `admin-window.html` | Central Admin Window |
| `admin-dashboard.html` | Admin overview |

---

## 🔧 Development Roadmap

### Phase 1 — Frontend

- [x] Homepage
- [x] Student Login
- [x] Student Dashboard
- [x] Faculty Login
- [x] Faculty Dashboard
- [x] Admin Login
- [x] Admin Dashboard
- [x] Admin Window
- [x] Student Management
- [x] Faculty Management
- [x] Course Management
- [x] Faculty-Course Assignment
- [x] Class & Timetable Management
- [x] Attendance Overview
- [x] Marks & Examination
- [x] Syllabus Monitoring
- [x] Academic Resources
- [x] Reports
- [x] User & Access Control
- [x] System Settings

### Phase 2 — Backend

- [ ] Backend architecture
- [ ] Database design
- [ ] Authentication
- [ ] Role-based authorization
- [ ] REST/API layer
- [ ] Student APIs
- [ ] Faculty APIs
- [ ] Course APIs
- [ ] Attendance APIs
- [ ] Examination APIs
- [ ] Resource APIs
- [ ] Reports APIs
- [ ] Admin APIs

### Phase 3 — Integration

- [ ] Connect frontend to APIs
- [ ] Replace demo data
- [ ] Persistent authentication
- [ ] Database CRUD operations
- [ ] Form validation
- [ ] Error handling
- [ ] Loading states
- [ ] API security

### Phase 4 — UI Enhancement

- [ ] Motion graphics
- [ ] Page transitions
- [ ] Advanced animations
- [ ] Animated charts
- [ ] Skeleton loading
- [ ] Micro-interactions
- [ ] UI performance optimization

### Phase 5 — Testing & Deployment

- [ ] Functional testing
- [ ] API testing
- [ ] Database testing
- [ ] Security testing
- [ ] Responsive testing
- [ ] Performance optimization
- [ ] Production deployment

---

## 🔒 Security

The current frontend authentication is a prototype and should **not** be considered production-secure.

Before production deployment, the system should implement:

- Secure password hashing
- Server-side authentication
- Session management
- Role-based access control
- Authorization checks
- Input validation
- API security
- Secure file uploads
- Audit logging
- Rate limiting
- HTTPS
- Secure environment variables

---

## 📌 Current Project Status

```text
Frontend UI        ████████████████████  Completed
Admin Modules      ████████████████████  Completed
Admin Integration  ████████████████████  Completed
Backend            ░░░░░░░░░░░░░░░░░░░░  Planned
Database           ░░░░░░░░░░░░░░░░░░░░  Planned
API Integration    ░░░░░░░░░░░░░░░░░░░░  Planned
Animations         ░░░░░░░░░░░░░░░░░░░░  Planned
Deployment         ░░░░░░░░░░░░░░░░░░░░  Planned
```

---

## 🤝 Development Approach

The system is being developed incrementally.

Major modules are separated into individual files so each component can be developed, tested and maintained independently.

The Admin Window acts as the central navigation layer rather than duplicating the source code of every Admin module.

---

## 📄 License

This project is currently an academic/project prototype.

Licensing terms can be updated when the project is prepared for public release.

---

## 👨‍💻 Project

**BWU — University Academic Management System**

A modular academic management platform designed to bring student, faculty and administrative workflows into one centralized system.
