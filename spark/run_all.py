import subprocess
import sys
import time

STEPS = ["spark.cohort", "spark.funnel", "spark.seller_rolling", "spark.verify"]

for step in STEPS:
    print(f"\n=== {step} ===")
    t = time.time()
    r = subprocess.run([sys.executable, "-m", step])
    if r.returncode != 0:
        print(f"FAILED: {step}")
        sys.exit(1)
    print(f"  done in {time.time() - t:.1f}s")

print("\nPhase 2 pipeline finished: all jobs ran and all checks passed.")