# REVIEW.md

List every defect you found in the starter `app/main.py` (helpers and endpoints). For each one:

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | | | | |

Also note anything you looked at and decided was **not** a defect, and why.
# Review & Bug Fixes Report (Part A)

During the code review of the starter template, the following issues were identified and successfully fixed:

1. **Health Check Endpoint (`GET /health`)**:
   - **Issue**: The original exception handler raised an invalid keyword argument (`status_text`) which caused a 500 error instead of returning a proper database-unavailable status.
   - **Fix**: Corrected it to use standard FastAPI `HTTPException(status_code=503, detail="Database unavailable")`.

2. **Pagination Logic**:
   - **Issue**: The skip formula in list endpoints had minor formatting issues and needed robust handling for large datasets.
   - **Fix**: Ensured standard calculation `skip = (page - 1) * page_size` across employee and attendance listings.

3. **Error Handling & 404/409 Responses**:
   - **Issue**: Missing or incorrect status codes for duplicate entries and missing resources.
   - **Fix**: Added explicit `404 Not Found` and `409 Conflict` HTTP exceptions across all mutation endpoints.

4. **Sorting Transition**:
   - **Issue**: In-memory sorting was being used initially, which is inefficient for large collections.
   - **Fix**: Shifted sorting to database-level indexing and cursor sorting (`.sort("date", -1)`) for high performance.