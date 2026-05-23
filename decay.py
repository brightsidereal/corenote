import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = "postgresql://postgres:postgres@localhost:5433/corenote"
DECAY_RATE = 0.8
NO_READ_DAYS = 30
COLD_THRESHOLD = 0.05
MIN_IMPORTANCE = 0.01

def run_decay(dry_run: bool = False):
    con = psycopg2.connect(DATABASE_URL)
    cur = con.cursor(cursor_factory=RealDictCursor)

    # bug #9 fix: ใช้ timezone-aware datetime
    cur.execute("""
        SELECT id, content, scope, importance, read_count, last_read_at
        FROM facts
        WHERE (last_read_at IS NULL OR last_read_at < NOW() - INTERVAL '%s days')
          AND importance > %s
        ORDER BY importance ASC
    """, (NO_READ_DAYS, MIN_IMPORTANCE))

    candidates = cur.fetchall()
    print(f"found {len(candidates)} facts eligible for decay")
    print(f"dry_run={dry_run}\n")

    decayed, cold = [], []

    for row in candidates:
        new_importance = round(row["importance"] * DECAY_RATE, 4)
        new_importance = max(new_importance, MIN_IMPORTANCE)
        status = "cold" if new_importance < COLD_THRESHOLD else "active"
        print(f"  [{status}] {row['scope']} — {row['content'][:50]}")
        print(f"          importance: {row['importance']} → {new_importance}")

        if status == "cold":
            cold.append(row["id"])
        else:
            decayed.append((new_importance, row["id"]))

    if not dry_run:
        for new_imp, fact_id in decayed:
            cur.execute("UPDATE facts SET importance = %s WHERE id = %s", (new_imp, fact_id))
        if cold:
            cur.execute("UPDATE facts SET importance = %s WHERE id = ANY(%s)", (MIN_IMPORTANCE, cold))
        con.commit()
        print(f"\ndone — decayed {len(decayed)}, moved to cold {len(cold)}")
    else:
        print(f"\n[dry run] would decay {len(decayed)}, move to cold {len(cold)}")

    cur.close()
    con.close()

if __name__ == "__main__":
    import sys
    dry_run = "--apply" not in sys.argv
    run_decay(dry_run=dry_run)