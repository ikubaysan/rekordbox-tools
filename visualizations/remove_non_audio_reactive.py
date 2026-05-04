import os
import re
import argparse

AUDIO_VARS = ["bass", "mid", "treb"]

# Regex for whole-word matching (case-insensitive)
AUDIO_REGEX = {
    var: re.compile(rf"\b{var}\b", re.IGNORECASE)
    for var in AUDIO_VARS
}


def is_audio_complete(filepath):
    """
    Returns:
        (is_valid, used_vars_set)
    """
    used = set()

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()

                # Skip comments
                if not line or line.startswith("//"):
                    continue

                for var, regex in AUDIO_REGEX.items():
                    if regex.search(line):
                        used.add(var)

                # Early exit if all found
                if len(used) == 3:
                    return True, used

    except Exception as e:
        print(f"[ERROR] Failed to read {filepath}: {e}")
        return False, used

    return len(used) == 3, used


def find_milk_files(root_dir):
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.lower().endswith(".milk"):
                yield os.path.join(root, file)


def main():
    parser = argparse.ArgumentParser(description="Filter MilkDrop presets by audio usage")
    parser.add_argument("directory", help="Root directory to scan")
    parser.add_argument("--dry-run", action="store_true", help="Do not delete files")
    parser.add_argument("--verbose", action="store_true", help="Print per-file decisions")

    args = parser.parse_args()

    total = 0
    valid = 0
    invalid = 0
    deleted = 0

    for filepath in find_milk_files(args.directory):
        total += 1

        is_valid, used = is_audio_complete(filepath)

        if is_valid:
            valid += 1
            if args.verbose:
                print(f"[KEEP] {filepath} (uses: {sorted(used)})")
        else:
            invalid += 1

            if args.verbose:
                print(f"[REMOVE] {filepath} (uses: {sorted(used)})")

            if not args.dry_run:
                try:
                    os.remove(filepath)
                    deleted += 1
                except Exception as e:
                    print(f"[ERROR] Failed to delete {filepath}: {e}")

    # Summary
    print("\n=== SUMMARY ===")
    print(f"Total files evaluated : {total}")
    print(f"Valid (kept)          : {valid}")
    print(f"Invalid (to remove)   : {invalid}")
    print(f"Actually deleted      : {deleted}")
    if args.dry_run:
        print("(Dry run: no files were deleted)")


if __name__ == "__main__":
    main()