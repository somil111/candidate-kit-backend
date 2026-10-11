# DECISIONS.md  (about 150-200 words in total - plain language, your own words)

1. **Indexes.** Which indexes did you create, and which query or guarantee does each one serve? Which one did you consider and reject?
2. **Punch-in race.** Two identical punch-in requests arrive at the same instant. Walk through exactly what happens in your code.
3. **Ties.** Two employees are tied on late minutes at the cutoff of `limit`. What does your leaderboard return, and why?
4. **Headcount.** How does your department summary make sure employees with zero logs are counted?
5. **One thing you would change** if this had to serve 100x the data.
# Architectural Decisions & Design Choices (Part C)

## 1. Database Indexing Strategy
- **Decision**: Created compound unique indexes on `attendance_logs` (`emp_code`, `date`) and single indexes on `employees` (`emp_code`, `department`).
- **Rationale**: Ensures O(1) uniqueness enforcement at the DB level, prevents race conditions during double punch-ins, and scales analytics performance across 100,000+ records.

## 2. Aggregation Pipelines for Analytics
- **Decision**: Utilized native MongoDB aggregation pipelines (`$match`, `$lookup`, `$group`, `$sum`) for monthly summaries, department summaries, and the late leaderboard.
- **Rationale**: Offloads computation directly to the database engine rather than fetching heavy payloads into application memory.

## 3. Regularization Audit Trail
- **Decision**: Implemented an immutable `history` array inside `attendance_logs` on every `PATCH` request.
- **Rationale**: Maintains a clear audit trail of previous values (`punch_in`, `punch_out`, status changes) for compliance and tracking.