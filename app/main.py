"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient
from fastapi.responses import RedirectResponse

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(hour=h, minute=m, second=0, microsecond=0)
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, status_text="Database unavailable")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    q = {}
    if department:
        q["department"] = department
    skip = (page-1) * page_size
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")
    ts = datetime.fromtimestamp(body.punched_at / 1000) if body.punched_at else datetime.now()
    d = ts.date().isoformat()
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    total = db.attendance_logs.count_documents(q)
    cursor = db.attendance_logs.find(q).sort("date", -1).skip((page - 1) * page_size).limit(page_size)
    items = []
    for d in cursor:
        d["id"] = str(d.pop("_id"))
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #

@app.on_event("startup")
def configure_indexes():
    # Create indexes idempotently for performance on 100k+ docs
    db.employees.create_index("emp_code", unique=True)
    db.employees.create_index("department")
    db.attendance_logs.create_index([("emp_code", 1), ("date", 1)], unique=True)
    db.attendance_logs.create_index("date")



class PunchOutIn(BaseModel):
    emp_code: str
    punched_out_at: Optional[int] = None


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")

    ts = datetime.fromtimestamp(body.punched_out_at / 1000) if body.punched_out_at else datetime.now()
    d = ts.date().isoformat()

    log = db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d})
    if not log:
        raise HTTPException(404, "No attendance record found for this date to punch out")

    if log.get("punch_out") is not None:
        raise HTTPException(409, "Already punched out for this date")

    punch_in_time = log["punch_in"]
    
   
    work_hours = compute_work_hours(punch_in_time, ts)
    overtime_minutes = compute_overtime(ts, emp["shift_end"], d)
    half_day = work_hours < 4.50

    db.attendance_logs.update_one(
        {"_id": log["_id"]},
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    updated_log = db.attendance_logs.find_one({"_id": log["_id"]})
    updated_log["id"] = str(updated_log.pop("_id"))
    return updated_log

class AttendanceUpdateIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: AttendanceUpdateIn):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")

    log = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not log:
        raise HTTPException(404, "Attendance record not found for this date")

    old_snapshot = {
        "status": log.get("status"),
        "punch_in": log.get("punch_in"),
        "punch_out": log.get("punch_out"),
        "work_hours": log.get("work_hours"),
        "late_minutes": log.get("late_minutes"),
        "overtime_minutes": log.get("overtime_minutes"),
        "half_day": log.get("half_day"),
    }

    update_fields = {}
    if body.status is not None:
        update_fields["status"] = body.status

    new_punch_in = log.get("punch_in")
    if body.punch_in is not None:
        new_punch_in = datetime.fromtimestamp(body.punch_in / 1000)
        update_fields["punch_in"] = new_punch_in
        update_fields["late_minutes"] = compute_late_minutes(new_punch_in, emp["shift_start"])

    new_punch_out = log.get("punch_out")
    if body.punch_out is not None:
        new_punch_out = datetime.fromtimestamp(body.punch_out / 1000)
        update_fields["punch_out"] = new_punch_out

    if new_punch_in and new_punch_out:
        wh = compute_work_hours(new_punch_in, new_punch_out)
        update_fields["work_hours"] = wh
        update_fields["overtime_minutes"] = compute_overtime(new_punch_out, emp["shift_end"], date)
        update_fields["half_day"] = wh < 4.50

    history_entry = {
        "modified_at": datetime.now(),
        "previous_values": old_snapshot,
    }

    db.attendance_logs.update_one(
        {"_id": log["_id"]},
        {
            "$set": update_fields,
            "$push": {"history": history_entry},
        },
    )

    updated_log = db.attendance_logs.find_one({"_id": log["_id"]})
    updated_log["id"] = str(updated_log.pop("_id"))
    return updated_log



@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_summary(emp_code: str, year: int, month: int):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")

    start_str = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end_str = f"{year+1:04d}-01-01"
    else:
        end_str = f"{year:04d}-{month+1:02d}-01"

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {"$gte": start_str, "$lt": end_str},
            }
        },
        {
            "$group": {
                "_id": None,
                "total_days_present": {
                    "$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}
                },
                "total_days_absent": {
                    "$sum": {"$cond": [{"$eq": ["$status", "ABSENT"]}, 1, 0]}
                },
                "total_days_leave": {
                    "$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}
                },
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {"$sum": "$overtime_minutes"},
                "total_work_hours": {"$sum": {"$ifNull": ["$work_hours", 0]}},
                "total_half_days": {
                    "$sum": {"$cond": [{"$eq": ["$half_day", True]}, 1, 0]}
                },
            }
        },
    ]

    result = list(db.attendance_logs.aggregate(pipeline))
    if not result:
        summary = {
            "emp_code": emp_code,
            "year": year,
            "month": month,
            "total_days_present": 0,
            "total_days_absent": 0,
            "total_days_leave": 0,
            "total_late_minutes": 0,
            "total_overtime_minutes": 0,
            "total_work_hours": 0.0,
            "total_half_days": 0,
        }
    else:
        summary = result[0]
        summary.pop("_id", None)
        summary["emp_code"] = emp_code
        summary["year"] = year
        summary["month"] = month
        summary["total_work_hours"] = round(summary["total_work_hours"], 2)

    return summary


@app.get("/analytics/departments/summary")
def department_summary(date: str):
    pipeline = [
        {"$match": {"date": date}},
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "emp_info",
            }
        },
        {"$unwind": "$emp_info"},
        {
            "$group": {
                "_id": "$emp_info.department",
                "headcount": {"$sum": 1},
                "present": {"$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}},
                "absent": {"$sum": {"$cond": [{"$eq": ["$status", "ABSENT"]}, 1, 0]}},
                "leave": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {"$sum": "$overtime_minutes"},
            }
        },
        {"$sort": {"_id": 1}},
    ]

    results = list(db.attendance_logs.aggregate(pipeline))
    departments = []
    for r in results:
        departments.append(
            {
                "department": r["_id"],
                "headcount": r["headcount"],
                "present": r["present"],
                "absent": r["absent"],
                "leave": r["leave"],
                "total_late_minutes": r["total_late_minutes"],
                "total_overtime_minutes": r["total_overtime_minutes"],
            }
        )
    return {"date": date, "departments": departments}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(date_from: str, date_to: str, limit: int = 10):
    pipeline = [
        {
            "$match": {
                "date": {"$gte": date_from, "$lte": date_to},
                "late_minutes": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }
        },
        {"$sort": {"total_late_minutes": -1, "late_count": -1}},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "emp_info",
            }
        },
        {"$unwind": "$emp_info"},
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$emp_info.name",
                "department": "$emp_info.department",
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
    ]

    items = list(db.attendance_logs.aggregate(pipeline))
    return {"date_from": date_from, "date_to": date_to, "items": items}


@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, date_from: str, date_to: str):
    # Verify department exists
    dept_emp_count = db.employees.count_documents({"department": department})
    if dept_emp_count == 0:
        raise HTTPException(404, "Department not found or has no employees")

    pipeline = [
        {
            "$match": {
                "date": {"$gte": date_from, "$lte": date_to},
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "emp_info",
            }
        },
        {"$unwind": "$emp_info"},
        {"$match": {"emp_info.department": department}},
        {
            "$group": {
                "_id": "$date",
                "present_count": {"$sum": {"$cond": [{"$eq": ["$status", "PRESENT"]}, 1, 0]}},
                "total_work_hours": {"$sum": {"$ifNull": ["$work_hours", 0]}},
            }
        },
        {"$sort": {"_id": 1}},
    ]

    data = list(db.attendance_logs.aggregate(pipeline))
    map_data = {row["_id"]: row for row in data}

    # Generate full date range series for gap filling
    start_date = datetime.fromisoformat(date_from).date()
    end_date = datetime.fromisoformat(date_to).date()
    delta = timedelta(days=1)

    trend_series = []
    current_date = start_date
    while current_date <= end_date:
        d_str = current_date.isoformat()
        if d_str in map_data:
            trend_series.append(
                {
                    "date": d_str,
                    "present_count": map_data[d_str]["present_count"],
                    "total_work_hours": round(map_data[d_str]["total_work_hours"], 2),
                }
            )
        else:
            trend_series.append(
                {
                    "date": d_str,
                    "present_count": 0,
                    "total_work_hours": 0.0,
                }
            )
        current_date += delta

    
    for i in range(len(trend_series)):
        window = trend_series[max(0, i - 6) : i + 1]
        avg = sum(item["present_count"] for item in window) / len(window)
        trend_series[i]["moving_avg_present"] = round(avg, 2)

    return {"department": department, "trend": trend_series}


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: str):
    if endpoint == "list_attendance":
        explain_res = db.attendance_logs.find({"emp_code": "EMP001"}).sort("date", -1).explain()
    elif endpoint == "department_summary":
        explain_res = db.attendance_logs.aggregate([
            {"$match": {"date": "2026-05-01"}},
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "emp_info",
                }
            }
        ]).explain()
    else:
        raise HTTPException(400, "Invalid endpoint name for explanation")
    return {"endpoint": endpoint, "explain": explain_res}
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")