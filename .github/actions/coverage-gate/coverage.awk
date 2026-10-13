# Sums lcov line coverage under PATH_PREFIX (excluding EXCLUDE_SUFFIXES).
# A function's 0-hit FN header line counts as covered when a later line
# of its body ran. Env: PATH_PREFIX, EXCLUDE_SUFFIXES, UNCOVERED_FILE.
# Prints "<covered> <total>"; writes one "file|count|ranges" row per file
# with uncovered lines to UNCOVERED_FILE, sorted by file. `ranges` joins
# runs of uncovered lines with no covered instrumented line between them
# ("63-104,110"), at most MAX_RUNS runs, then "+N more".
# Known limit: an unused inline-assembly function inside a Solidity
# function body counts as covered when a later line of that body ran.

BEGIN {
    MAX_RUNS = 8
    out_file = ENVIRON["UNCOVERED_FILE"]
    if (out_file == "") out_file = "uncovered.txt"
    n_ex = split(ENVIRON["EXCLUDE_SUFFIXES"], ex, " ")
    covered = 0
    total = 0
    in_scope = 0
    n_files = 0
    # truncate/create the output file up front so a run with zero
    # uncovered entries never leaves a stale file behind.
    printf "" > out_file
    close(out_file)
}

function is_excluded(path,    i, suf, plen, slen) {
    for (i = 1; i <= n_ex; i++) {
        suf = ex[i]
        if (suf == "") continue
        slen = length(suf)
        plen = length(path)
        if (plen >= slen && substr(path, plen - slen + 1) == suf) return 1
    }
    return 0
}

function reset_record() {
    delete fnline
    n_fn = 0
    delete daline
    delete dahits
    delete dacov
    n_da = 0
}

/^SF:/ {
    flush_record()
    cur_file = substr($0, 4)
    reset_record()
    prefix = ENVIRON["PATH_PREFIX"]
    in_scope = (index(cur_file, prefix) == 1) && !is_excluded(cur_file)
    next
}

/^FN:/ {
    if (!in_scope) next
    split(substr($0, 4), parts, ",")
    n_fn++
    fnline[n_fn] = parts[1] + 0
    next
}

/^DA:/ {
    if (!in_scope) next
    split(substr($0, 4), parts, ",")
    n_da++
    daline[n_da] = parts[1] + 0
    dahits[n_da] = parts[2] + 0
    next
}

/^LF:/ {
    if (!in_scope) next
    total += substr($0, 4) + 0
    next
}

/^end_of_record/ {
    flush_record()
    in_scope = 0
    next
}

function next_fn_line(line,    j, best) {
    best = -1
    for (j = 1; j <= n_fn; j++) {
        if (fnline[j] > line && (best == -1 || fnline[j] < best)) best = fnline[j]
    }
    return best
}

function is_fn_header(line,    j) {
    for (j = 1; j <= n_fn; j++) if (fnline[j] == line) return 1
    return 0
}

function body_hit(lo, hi,    k) {
    for (k = 1; k <= n_da; k++) {
        if (daline[k] > lo && (hi == -1 || daline[k] < hi) && dahits[k] > 0) return 1
    }
    return 0
}

function flush_record(    i, j, line, hits, nfl, kl, kc, count, runs, n_runs, run_lo, run_hi, open_run) {
    if (!in_scope) return
    for (i = 1; i <= n_da; i++) {
        line = daline[i]
        hits = dahits[i]
        dacov[i] = 1
        if (hits > 0) {
            covered++
            continue
        }
        if (is_fn_header(line)) {
            nfl = next_fn_line(line)
            if (body_hit(line, nfl)) {
                covered++
                continue
            }
        }
        dacov[i] = 0
    }
    # insertion sort by line; a record holds one file's lines, small enough
    # in practice for O(n^2) and awk-portable.
    for (i = 2; i <= n_da; i++) {
        kl = daline[i]; kc = dacov[i]
        j = i - 1
        while (j >= 1 && daline[j] > kl) {
            daline[j+1] = daline[j]; dacov[j+1] = dacov[j]
            j--
        }
        daline[j+1] = kl; dacov[j+1] = kc
    }
    count = 0; n_runs = 0; runs = ""; open_run = 0
    for (i = 1; i <= n_da + 1; i++) {
        if (i <= n_da && !dacov[i]) {
            count++
            if (!open_run) { run_lo = daline[i]; open_run = 1 }
            run_hi = daline[i]
            continue
        }
        if (open_run) {
            n_runs++
            if (n_runs <= MAX_RUNS)
                runs = runs (runs == "" ? "" : ",") (run_lo == run_hi ? run_lo : run_lo "-" run_hi)
            open_run = 0
        }
    }
    if (count == 0) return
    if (n_runs > MAX_RUNS) runs = runs ",+" (n_runs - MAX_RUNS) " more"
    n_files++
    rf[n_files] = cur_file
    rrow[n_files] = cur_file "|" count "|" runs
}

END {
    flush_record()
    for (i = 2; i <= n_files; i++) {
        kf = rf[i]; kr = rrow[i]
        j = i - 1
        while (j >= 1 && rf[j] > kf) {
            rf[j+1] = rf[j]; rrow[j+1] = rrow[j]
            j--
        }
        rf[j+1] = kf; rrow[j+1] = kr
    }
    for (i = 1; i <= n_files; i++) print rrow[i] >> out_file
    close(out_file)
    print covered " " total
}
