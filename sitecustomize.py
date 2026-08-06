import sys

# Temporary exact-date override for the 2026-08-06 workbook build.
sys.argv = [arg.replace("2026-08-05", "2026-08-06") for arg in sys.argv]
