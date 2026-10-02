from fastapi import APIRouter

from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.users import router as users_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)

api_router.include_router(users_router)
from app.routers.academic import (  # noqa: E402
    departments_router,
    programs_router,
    semesters_router,
    sessions_router,
)

for _r in (departments_router, programs_router, sessions_router, semesters_router):
    api_router.include_router(_r)

from app.routers.courses import courses_router, offerings_router  # noqa: E402

api_router.include_router(courses_router)
api_router.include_router(offerings_router)

from app.routers.people import enrollments_router, faculty_router, students_router  # noqa: E402

for _r in (students_router, faculty_router, enrollments_router):
    api_router.include_router(_r)

from app.routers.attendance import router as attendance_router  # noqa: E402

api_router.include_router(attendance_router)

from app.routers.exams import examinations_router, schedules_router  # noqa: E402

api_router.include_router(examinations_router)
api_router.include_router(schedules_router)

from app.routers.results import grading_router, marks_router, results_router  # noqa: E402

for _r in (grading_router, marks_router, results_router):
    api_router.include_router(_r)

from app.routers.timetable import router as timetable_router  # noqa: E402
from app.routers.notices import router as notices_router  # noqa: E402

api_router.include_router(timetable_router)
api_router.include_router(notices_router)

from app.routers.ops import analytics_router, audit_router, reports_router, sessions_router  # noqa: E402

for _r in (audit_router, sessions_router, analytics_router, reports_router):
    api_router.include_router(_r)
