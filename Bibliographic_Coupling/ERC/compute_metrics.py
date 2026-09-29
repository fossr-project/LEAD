# -*- coding: UTF-8 -*-
"""
Step 05: evaluates, on a TSV file produced by step 04
(data/output/overlap/step04_<mode>_<collection>_<ys>-<ye>.tsv), how well
the citation overlap percentage predicts the "match" field (ground
truth: 1 = correct candidate auid, 0 = wrong candidate auid).


INPUT FILE (-f/--tsv-file)

If not specified, shows a numbered list of the *.tsv files present in
data/output/overlap/ and asks the user to choose one, or to choose "all
files", or to choose "a list of files" (entering the numbers separated
by commas, e.g. 1,3,4): in this case the evaluation (fixed or auto
threshold) is done only on the indicated files, with the same logic used
for "all files" (see below), applied however only to the chosen subset.


THRESHOLD (-th/--threshold)

Number in (0, 1], default 0.5. For each row of the TSV, the prediction is:
  prediction = 1  if (percentage / 100) >= threshold
  prediction = 0  otherwise

Rows with percentage == -1 (panel/domain not computed by step 03, see
step 04) are excluded from the evaluation.

With --threshold auto, instead of a fixed value, all thresholds from 0.01
to 1.00 in steps of 0.01 (100 values) are explored and the one that
maximizes the f1-score of class 1 (correct match) is chosen. In case of a
tie between several thresholds, the lowest one is kept.

If a single file was chosen, the evaluation (fixed or auto threshold)
covers only that file. If "all files" were chosen:
  - with a fixed threshold, the same threshold is applied to each file,
    evaluated separately (the files are not merged into a single
    evaluation: they represent different populations/granularities -
    panel vs domain, surname vs surname_initial - and mixing them would
    not make sense);
  - with --threshold auto, a SINGLE shared threshold is searched across
    all files: for each candidate threshold (0.01-1.00) the f1-score of
    class 1 is computed on each file, the files are AVERAGED, and the
    threshold with the highest average is chosen. That shared threshold
    is then used to print the confusion matrix and classification report
    of each file individually.


OUTPUT

The prediction is compared with the "match" field (ground truth) of each
row. Printed, in this order:
  1. the confusion matrix (actual x predicted);
  2. a classification report with precision/recall/f1-score for the two
     classes (0 = wrong match, 1 = correct match), overall accuracy, and
     the macro/weighted averages (overall).
"""
import argparse
import csv
import glob
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OVERLAP_ROOT = os.path.join(SCRIPT_DIR, "data", "output", "overlap")
DEFAULT_THRESHOLD = 0.5


def rel(path):
    """path relative to SCRIPT_DIR, only for display in the help text."""
    return os.path.relpath(path, SCRIPT_DIR)


def threshold_type(value):
    if value == "auto":
        return "auto"
    f = float(value)
    if not (0 < f <= 1):
        raise argparse.ArgumentTypeError(
            f"threshold must be 'auto' or a number > 0 and <= 1, got: {value}"
        )
    return f


def choose_files_by_list(files):
    """asks for a comma-separated list of numbers and returns the
    corresponding files, in the order given by the user."""
    while True:
        raw = input(f"file numbers separated by commas (1-{len(files)}, e.g. 1,3,4): ").strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts and all(p.isdigit() and 1 <= int(p) <= len(files) for p in parts):
            return [files[int(p) - 1] for p in parts]
        print(f"invalid input: use numbers from 1 to {len(files)} separated by commas.")


def choose_files_interactively(root):
    """shows the numbered list of .tsv files in root, plus two additional
    options ("all files" and "a list of files"), and always returns a
    list of paths (a single element if the user chooses a specific
    file)."""
    files = sorted(glob.glob(os.path.join(root, "*.tsv")))
    if not files:
        raise SystemExit(f"no .tsv file found in {root}")

    all_option = len(files) + 1
    list_option = len(files) + 2

    print(f"files available in {root}:")
    for i, fn in enumerate(files, start=1):
        print(f"  {i}) {os.path.basename(fn)}")
    print(f"  {all_option}) all files (evaluate each one separately)")
    print(f"  {list_option}) a list of files (numbers separated by commas, e.g. 1,3,4)")

    while True:
        choice = input(f"choose an option [1-{list_option}]: ").strip()
        if choice.isdigit():
            choice = int(choice)
            if 1 <= choice <= len(files):
                return [files[choice - 1]]
            if choice == all_option:
                return files
            if choice == list_option:
                return choose_files_by_list(files)
        print("invalid choice, try again.")


def load_true_and_percentages(tsv_file):
    """reads the tsv and returns (y_true, percentages, n_total, n_skipped),
    excluding rows with percentage == -1."""
    with open(tsv_file, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    y_true = []
    percentages = []
    n_skipped = 0
    for row in rows:
        percentage = float(row["percentage"])
        if percentage == -1:
            n_skipped += 1
            continue
        y_true.append(int(row["match"]))
        percentages.append(percentage)

    return y_true, percentages, len(rows), n_skipped


def predict(percentages, threshold):
    return [1 if (p / 100.0) >= threshold else 0 for p in percentages]


def f1_of_class_1(y_true, y_pred):
    tp, fp, fn, tn = confusion_counts(y_true, y_pred)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    return safe_div(2 * precision * recall, precision + recall)


def find_best_threshold(y_true, percentages):
    """explores the thresholds from 0.01 to 1.00 (step 0.01) and returns
    the one that maximizes the f1-score of class 1; in case of a tie
    keeps the lowest one (first found, scanning in increasing order)."""
    best_threshold = None
    best_f1 = -1
    for i in range(1, 101):
        threshold = i / 100.0
        y_pred = predict(percentages, threshold)
        f1 = f1_of_class_1(y_true, y_pred)
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold
    return best_threshold, best_f1


def find_shared_best_threshold(files_data):
    """explores the thresholds from 0.01 to 1.00 (step 0.01) and returns
    the one that maximizes the AVERAGE (across the files in files_data, a
    list of (y_true, percentages)) f1-score of class 1; in case of a tie
    keeps the lowest one."""
    best_threshold = None
    best_avg_f1 = -1
    for i in range(1, 101):
        threshold = i / 100.0
        f1_scores = [
            f1_of_class_1(y_true, predict(percentages, threshold))
            for y_true, percentages in files_data
        ]
        avg_f1 = sum(f1_scores) / len(f1_scores)
        if avg_f1 > best_avg_f1:
            best_avg_f1 = avg_f1
            best_threshold = threshold
    return best_threshold, best_avg_f1


def confusion_counts(y_true, y_pred):
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    return tp, fp, fn, tn


def safe_div(a, b):
    return a / b if b else 0.0


def print_confusion_matrix(tp, fp, fn, tn):
    print("=== confusion matrix ===")
    print(f"{'':>16}{'pred. 0':>10}{'pred. 1':>10}")
    print(f"{'actual 0':>16}{tn:>10}{fp:>10}")
    print(f"{'actual 1':>16}{fn:>10}{tp:>10}")


def print_classification_report(tp, fp, fn, tn):
    n_eval = tp + fp + fn + tn

    precision_1 = safe_div(tp, tp + fp)
    recall_1 = safe_div(tp, tp + fn)
    f1_1 = safe_div(2 * precision_1 * recall_1, precision_1 + recall_1)
    support_1 = tp + fn

    precision_0 = safe_div(tn, tn + fn)
    recall_0 = safe_div(tn, tn + fp)
    f1_0 = safe_div(2 * precision_0 * recall_0, precision_0 + recall_0)
    support_0 = tn + fp

    accuracy = safe_div(tp + tn, n_eval)

    macro_precision = (precision_0 + precision_1) / 2
    macro_recall = (recall_0 + recall_1) / 2
    macro_f1 = (f1_0 + f1_1) / 2

    weighted_precision = safe_div(precision_0 * support_0 + precision_1 * support_1, n_eval)
    weighted_recall = safe_div(recall_0 * support_0 + recall_1 * support_1, n_eval)
    weighted_f1 = safe_div(f1_0 * support_0 + f1_1 * support_1, n_eval)

    print("=== classification report ===")
    print(f"{'':>22}{'precision':>10}{'recall':>10}{'f1-score':>10}{'support':>10}")
    print(f"{'0 (wrong match)':>22}{precision_0:>10.3f}{recall_0:>10.3f}{f1_0:>10.3f}{support_0:>10}")
    print(f"{'1 (correct match)':>22}{precision_1:>10.3f}{recall_1:>10.3f}{f1_1:>10.3f}{support_1:>10}")
    print()
    print(f"{'accuracy':>22}{'':>10}{'':>10}{accuracy:>10.3f}{n_eval:>10}")
    print(f"{'macro avg':>22}{macro_precision:>10.3f}{macro_recall:>10.3f}{macro_f1:>10.3f}{n_eval:>10}")
    print(f"{'weighted avg':>22}{weighted_precision:>10.3f}{weighted_recall:>10.3f}{weighted_f1:>10.3f}{n_eval:>10}")


def evaluate_file(tsv_file, threshold_arg):
    """runs the full evaluation (loading, possible auto threshold search,
    confusion matrix, classification report) on a file."""
    y_true, percentages, n_total, n_skipped = load_true_and_percentages(tsv_file)

    print(f"file: {tsv_file}")
    print(f"total rows: {n_total}, evaluated: {len(y_true)}, excluded (percentage == -1): {n_skipped}")

    if threshold_arg == "auto":
        threshold, best_f1 = find_best_threshold(y_true, percentages)
        print(f"threshold: auto -> {threshold:.2f} (f1-score class 1 = {best_f1:.3f})")
    else:
        threshold = threshold_arg
        print(f"threshold: {threshold}")
    print()

    y_pred = predict(percentages, threshold)

    tp, fp, fn, tn = confusion_counts(y_true, y_pred)
    print_confusion_matrix(tp, fp, fn, tn)
    print()
    print_classification_report(tp, fp, fn, tn)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-f", "--tsv-file",
        default=None,
        help="step 04 TSV file to evaluate (default: interactive numbered "
             f"list among the .tsv files in {rel(DEFAULT_OVERLAP_ROOT)}, with "
             f"an extra option to evaluate all of them)",
    )
    parser.add_argument(
        "-th", "--threshold",
        type=threshold_type,
        default=DEFAULT_THRESHOLD,
        help=f"threshold (0, 1] on the overlap percentage for the prediction, or "
             f"'auto' to search for the one that maximizes the f1-score of class 1 "
             f"(default: {DEFAULT_THRESHOLD})",
    )
    args = parser.parse_args()

    tsv_files = [args.tsv_file] if args.tsv_file else choose_files_interactively(DEFAULT_OVERLAP_ROOT)

    threshold_per_file = args.threshold
    if len(tsv_files) > 1 and args.threshold == "auto":
        files_data = [load_true_and_percentages(f)[:2] for f in tsv_files]
        shared_threshold, avg_f1 = find_shared_best_threshold(files_data)
        print(f"=== shared threshold search (average f1-score class 1 across {len(tsv_files)} files) ===")
        print(f"chosen threshold: {shared_threshold:.2f} (average f1 class 1 = {avg_f1:.3f})")
        print()
        threshold_per_file = shared_threshold

    for i, tsv_file in enumerate(tsv_files):
        if len(tsv_files) > 1:
            if i > 0:
                print()
            print(f"{'#' * 10} file {i + 1}/{len(tsv_files)} {'#' * 10}")
        evaluate_file(tsv_file, threshold_per_file)


if __name__ == "__main__":
    main()
