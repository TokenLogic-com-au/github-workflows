# Sums lcov line coverage under PATH_PREFIX (excluding EXCLUDE_SUFFIXES).
# A function's 0-hit FN header line counts as covered when a later line
# of its body ran. Env: PATH_PREFIX, EXCLUDE_SUFFIXES, SAMPLE_FILE.
# Prints "<covered> <total>"; writes up to 15 sorted "file:line" to SAMPLE_FILE.
# Known limit: an unused inline-assembly function inside a Solidity
# function body counts as covered when a later line of that body ran.

BEGIN {
    sample_file = ENVIRON["SAMPLE_FILE"]
    if (sample_file == "") sample_file = "uncovered_sample.txt"
    n_ex = split(ENVIRON["EXCLUDE_SUFFIXES"], ex, " ")
    covered = 0
    total = 0
    in_scope = 0
    n_uncovered = 0
    # truncate/create the sample file up front so a run with zero
    # uncovered entries never leaves a stale file behind.
    printf "" > sample_file
    close(sample_file)
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

function flush_record(    i, line, hits, nfl) {
    if (!in_scope) return
    for (i = 1; i <= n_da; i++) {
        line = daline[i]
        hits = dahits[i]
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
        n_uncovered++
        uf[n_uncovered] = cur_file
        ul[n_uncovered] = line
    }
}

END {
    flush_record()
    # insertion sort by file then numeric line; n_uncovered is small
    # enough in practice that O(n^2) is fine and stays awk-portable.
    for (i = 2; i <= n_uncovered; i++) {
        kf = uf[i]; kl = ul[i]
        j = i - 1
        while (j >= 1 && (uf[j] > kf || (uf[j] == kf && ul[j] + 0 > kl + 0))) {
            uf[j+1] = uf[j]; ul[j+1] = ul[j]
            j--
        }
        uf[j+1] = kf; ul[j+1] = kl
    }
    cap = (n_uncovered < 15) ? n_uncovered : 15
    for (i = 1; i <= cap; i++) {
        print uf[i] ":" ul[i] >> sample_file
    }
    close(sample_file)
    print covered " " total
}
