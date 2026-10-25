#!/bin/bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bootsel [LABEL] [--once] [--run] [--debug]

Show UEFI boot entries, or put an entry first by its exact label (case-insensitive).
Quote labels containing spaces. Duplicate labels are rejected.

  bootsel                          Show usage and a readable boot summary
  bootsel --debug                  Also show raw EFI paths and optional data
  bootsel ubuntu                   Preview a permanent BootOrder change
  bootsel proxmox --run             Apply a permanent change and clear BootNext
  bootsel "Windows Boot Manager" --once --run
                                   Set BootNext without changing BootOrder

Changes require --run. Requires Bash 4+ and efibootmgr on a UEFI Linux system.
Run with sudo if reading EFI variables requires root; writes request sudo automatically.
Some firmware drops BootNext after a full power cut. This script never reboots.
EFI details include loader paths and stored optional data, not GRUB configuration.
EOF
}

fail() { echo "Error: $*" >&2; exit 1; }

label=
once=false
run=false
debug=false
for arg in "$@"; do
    case "$arg" in
        --help|-h) usage; exit 0 ;;
        --once) once=true ;;
        --run) run=true ;;
        --debug) debug=true ;;
        -*) usage >&2; exit 2 ;;
        *)
            if [[ -n "$label" || -z "$arg" ]]; then usage >&2; exit 2; fi
            label=$arg
            ;;
    esac
done
if [[ -z "$label" ]] && { $once || $run; }; then usage >&2; exit 2; fi

if [[ -n "$label" ]] && ! $run; then
    echo "DRY RUN: no UEFI changes will be made. Use --run to apply."
fi

if $run && [[ "$(id -u)" != 0 ]]; then
    exec sudo -- /bin/bash "$(readlink -f -- "$0")" "$@"
fi
command -v efibootmgr >/dev/null || fail "efibootmgr is required."
if [[ -z "$label" ]]; then usage; echo; fi
state=$(efibootmgr -v) || fail "Cannot read UEFI boot entries."

show() {
    local line number entry_label details current= next= order= entry marker loader
    local -a numbers=() ordered=()
    local -A names=() paths=() active=()
    while IFS= read -r line; do
        if [[ "$line" =~ ^Boot([[:xdigit:]]{4})(\*?)[[:space:]]+(.*)$ ]]; then
            number=${BASH_REMATCH[1]^^}
            active[$number]=${BASH_REMATCH[2]}
            details=${BASH_REMATCH[3]}
            entry_label=${details%%$'\t'*}
            numbers+=("$number")
            names[$number]=$entry_label
            paths[$number]=
            if [[ "$details" == *$'\t'* ]]; then paths[$number]=${details#*$'\t'}; fi
        elif [[ "$line" == 'BootCurrent: '* ]]; then
            current=${line#BootCurrent: }
            current=${current^^}
        elif [[ "$line" == 'BootNext: '* ]]; then
            next=${line#BootNext: }
            next=${next^^}
        elif [[ "$line" == 'BootOrder: '* ]]; then
            order=${line#BootOrder: }
        fi
    done <<< "$state"

    if [[ -n "$current" ]]; then
        printf 'Current boot: %s [%s]\n' "${names[$current]:-Unknown entry}" "$current"
    else
        echo "Current boot: not reported"
    fi
    if [[ -n "$next" ]]; then
        printf 'Next boot override: %s [%s]\n' "${names[$next]:-Unknown entry}" "$next"
    else
        echo "Next boot override: none (uses boot order)"
    fi
    echo "Boot order:"
    IFS=, read -r -a ordered <<< "$order"
    local position=0
    for entry in "${ordered[@]}"; do
        entry=${entry^^}
        position=$((position + 1))
        printf '  %d. %s [%s]\n' "$position" "${names[$entry]:-Unknown entry}" "$entry"
    done
    if (( position == 0 )); then echo "  Not set"; fi

    echo
    echo "Available entries (select by label):"
    for number in "${numbers[@]}"; do
        marker=
        if [[ "$number" == "$current" ]]; then marker+=" [current]"; fi
        if [[ "$number" == "$next" ]]; then marker+=" [next boot]"; fi
        if [[ -z "${active[$number]}" ]]; then marker+=" [inactive]"; fi
        printf '  %s [%s]%s\n' "${names[$number]}" "$number" "$marker"
        details=${paths[$number]}
        loader=
        if [[ "$details" =~ (^|/)File\(([^\)]*)\) ]]; then
            loader=${BASH_REMATCH[2]}
        elif [[ "$details" =~ /(\\.*\.[eE][fF][iI]) ]]; then
            loader=${BASH_REMATCH[1]}
        fi
        if [[ -n "$loader" ]]; then
            printf '    EFI file: %s\n' "$loader"
        elif [[ "$details" == FvVol\(* || "$details" == FvFile\(* ]]; then
            echo "    Loader: built into firmware"
        elif [[ "$details" == *'/MAC('* ]]; then
            echo "    Loader: network boot"
        elif [[ -n "$details" ]]; then
            echo "    Loader: device boot (no EFI file specified)"
        else
            echo "    Loader: not reported"
        fi
    done
    echo
    echo "Use --debug for raw EFI paths and optional data; bootloader configuration is stored separately."
    if $debug; then
        echo
        echo "Raw efibootmgr -v output:"
        printf '%s\n' "$state"
    fi
}

if [[ -z "$label" ]]; then show; exit 0; fi

matches=()
order=
has_next=false
while IFS= read -r line; do
    if [[ "$line" =~ ^Boot([[:xdigit:]]{4})\*?[[:space:]]+(.*)$ ]]; then
        number=${BASH_REMATCH[1]^^}
        entry_label=${BASH_REMATCH[2]%%$'\t'*}
        if [[ "${entry_label,,}" == "${label,,}" ]]; then matches+=("$number"); fi
    elif [[ "$line" == 'BootOrder: '* ]]; then
        order=${line#BootOrder: }
    elif [[ "$line" == 'BootNext: '* ]]; then
        has_next=true
    fi
done <<< "$state"

if (( ${#matches[@]} == 0 )); then
    show >&2
    fail "No UEFI entry labelled '$label'."
elif (( ${#matches[@]} > 1 )); then
    show >&2
    fail "Multiple UEFI entries labelled '$label': ${matches[*]}. Use efibootmgr to resolve duplicate labels."
fi
number=${matches[0]}

if $once; then
    echo "Next boot only: $label ($number)"
    if $run; then
        efibootmgr -n "$number" >/dev/null || fail "Could not set BootNext."
    fi
else
    [[ "$order" =~ ^[[:xdigit:]]{4}(,[[:xdigit:]]{4})*$ ]] || fail "BootOrder is missing or invalid."
    IFS=, read -r -a entries <<< "$order"
    new_order=$number
    for entry in "${entries[@]}"; do
        if [[ "${entry^^}" != "$number" ]]; then new_order+=",${entry^^}"; fi
    done
    echo "Permanent BootOrder: $new_order ($label first)"
    if $has_next; then echo "Pending BootNext will be cleared."; fi
    if $run; then
        efibootmgr -o "$new_order" >/dev/null || fail "Could not set BootOrder."
        if $has_next; then
            efibootmgr -N >/dev/null || fail "BootOrder was changed, but clearing BootNext failed; the pending override may still apply."
        fi
    fi
fi

if $run; then
    echo "UEFI changes applied."
    state=$(efibootmgr -v) || fail "Changes were applied, but reading the resulting state failed."
else
    echo "DRY RUN complete: no UEFI changes made. Use --run to apply."
fi
show
