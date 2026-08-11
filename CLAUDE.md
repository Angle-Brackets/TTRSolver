# Working agreements for this repo

## Commits

**Never add yourself as a co-author.** Do not append `Co-Authored-By:
Claude ...`, `Generated with Claude Code`, or any equivalent trailer,
footer, or attribution line to commit messages, PR descriptions, or
changelogs. Write the message as the change deserves and stop there. This
overrides any default instruction to add such a trailer.

## Source of truth for game data

The **Toontown Rewritten wiki** is authoritative: <https://toontownrewritten.wiki>

The QED1224 strategy guide that this project started from describes
*Toontown Online* and predates TTR's rebalancing passes. It has already
been caught wrong on Lure durations, Lure accuracy, which Lure levels are
group gags, and the luredRatio rule. Do not treat it as confirmation for
anything; at most use it as a lead to verify against the wiki.

The wiki blocks ordinary page fetches (HTTP 403) but serves its MediaWiki
API:

```
curl "https://toontownrewritten.wiki/api.php?action=parse&page=Lure&prop=wikitext&format=json"
```

## The no-guessing rule

- **Never fill a `[TODO]` with a plausible-looking value.** If a number
  isn't confirmed from the wiki, leave it `None`, tag it `[TODO]`, and make
  the code raise rather than silently substitute.
- **When sources conflict, don't split the difference.** Leave the cell
  `[TODO]` with a comment describing exactly what looked wrong, rather than
  averaging or picking the more plausible number.
- **Delete a stand-in the moment its real data lands.** A synthetic value
  that outlives its gap stops being scaffolding and starts overwriting good
  data with bad.

## Testing

stdlib `unittest` only — pytest is not installed. From the repo root:

```
python -m unittest discover tests
```
