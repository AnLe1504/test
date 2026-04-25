-- One-time schema change to add per-user ownership to the three managed=False
-- tables. Run on the Railway Postgres once after deploying user-isolation code:
--   railway run python manage.py dbshell < core/migrations/add_user_columns.sql
-- (or paste into the Retool/psql shell).

ALTER TABLE trips           ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES auth_user(id) ON DELETE CASCADE;
ALTER TABLE circuit_visits  ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES auth_user(id) ON DELETE CASCADE;
ALTER TABLE bucket_list     ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES auth_user(id) ON DELETE CASCADE;

-- Assign all existing rows to the superuser (user id = 1) so no data is orphaned.
UPDATE trips           SET user_id = 1 WHERE user_id IS NULL;
UPDATE circuit_visits  SET user_id = 1 WHERE user_id IS NULL;
UPDATE bucket_list     SET user_id = 1 WHERE user_id IS NULL;

-- Helpful indexes for the per-user filtering done in core/views.py.
CREATE INDEX IF NOT EXISTS trips_user_id_idx          ON trips(user_id);
CREATE INDEX IF NOT EXISTS circuit_visits_user_id_idx ON circuit_visits(user_id);
CREATE INDEX IF NOT EXISTS bucket_list_user_id_idx    ON bucket_list(user_id);
