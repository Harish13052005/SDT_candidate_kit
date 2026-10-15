# DECISIONS.md

1. **Indexes.**
We created unique index `employees(emp_code)` for identity, and `employees(department, joined_on)` for summary filtering. On `attendance_logs`, we created unique `(emp_code, date)` to guarantee one daily log, `(date: -1, emp_code: 1)` for paginated listing, and `(emp_code, punch_out, punch_in)` for atomic punch-outs. We considered indexing `status` alone on logs but rejected it due to low cardinality.

2. **Punch-in race.**
Both concurrent requests derive the same attendance date and attempt an `insert_one`. The unique compound index on `(emp_code, date)` allows exactly one insert to succeed (HTTP 201) and fails the other with a `DuplicateKeyError`, which our exception handler intercepts to immediately return HTTP 409 Conflict.

3. **Ties.**
Using MongoDB's `$rank` window function, tied employees share the same rank (standard competition ranking: 1, 2, 2, 4). Filtering `rank <= limit` occurs after ranking, so all employees tied at or below the threshold are included, correctly returning more than `limit` rows when ties occur at the cutoff.

4. **Headcount.**
The pipeline originates on `employees` (filtering `joined_on <= month_end`) and performs a `$lookup` into `attendance_logs`. Grouping occurs over employees first, ensuring every employee joined by the deadline contributes to headcount even with zero attendance records.

5. **100x Data Change.**
At 100x scale (~10M logs), we would precompute daily/monthly rollups via event-driven background workers rather than computing on-demand aggregations across un-sharded collections.

6. **Department trend.**
The trend query starts from a one-day `$documents` anchor, uses `$densify` to generate the requested date range, and calculates headcount, daily attendance, and the seven-day moving average in MongoDB. This includes days with no attendance records without loading department employees or generating dates in Python. Rates use `$floor(value * 10000 + 0.5) / 10000` to preserve half-up rounding.
