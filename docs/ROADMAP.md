# Roadmap

Updated 28 September 2026. Current release: v9.5 "Dearg", 3424 ±10 on pool-F.

The aim for the next few releases is 3500 on the pool. Tuning should get part
of the way there, and a new generation of training data the rest.

## How it got here

Sgurr was 3012 in August. Most of the 400 Elo since then came from search work:
tuning, bug fixes, rebuilt time management, and in late September move
ordering, correction history, better reductions and a bucketed hash table. The
network has been trained on the same 102 million Gen9 positions since v9.0, and
has not changed at all since v9.2.

Changing the network's shape, by making it wider or adding king buckets, has
measured flat every time at the data sizes available. More data has always
paid.

## v9.5 to CCRL

v9.5's public binaries played 60 games at CCRL Blitz's 2'+1" with no losses on
time and no abnormal endings. It goes to CCRL once the GitHub release is up.
Later versions get sent only when they are clearly stronger.

## v9.6: tuning

- A tune of 48 search parameters at 8+0.08, many of them new in v9.5 and set
  by hand. An SPRT against v9.5 decides whether the tuned values ship.
- A tune of the time-management constants at 10+0.1.
- A check at a longer time control against v9.5. Nearly all testing so far
  has used 8 or 10 seconds a game.
- Two or three stronger engines for the pool, rated about 3450 to 3550 on CCRL
  Blitz. Only two of pool-F's sixteen are above v9.5, so its next run would
  say little without them.

I expect v9.6 to gain 10 to 30 Elo.

## Search changes still to try

| change | expected |
|---|---|
| let a hash table bound tighten the static eval | +2 to +8 |
| ProbCut | +5 to +15 |
| history that knows which squares are attacked | +5 to +15 |

None of these is large, so each goes in on its own SPRT, between the bigger
jobs.

## v10: Gen10 data

The network is the biggest lever left. Gen9 was labelled by v8's network at
150,000 nodes a position. Gen10 will be labelled by v9.6, several hundred Elo
stronger, and should be two to three times larger. At Gen9's pace of about two
weeks per hundred million positions, that is four to six weeks in which the
machine does little else, so it starts once v9.6 has shipped.

Width and king buckets get another test only once the data is several times
larger. The experiment below suggests they need a billion positions or more.

Network results are the hardest to predict. Two trainings on the same data
with different seeds have differed by 14 Elo, so a network change under about
20 needs several seeds before it counts. A reasonable hope for Gen10 is 30 to
60 Elo.

## The external-data experiment

Sgurr-X is the same engine with networks trained on public Stockfish-labelled
positions. A 512-wide network trained on about 1.2 billion of them beat v9.0's
own network by 86 Elo at the same search. It stays private while the terms of
that data are unclear, and the main line stays trained on Sgurr's own games.
Its use is as a measure of how far more data could take the main network.

## Housekeeping

- Put v9.0 on pool-F, so the web app shows a measured rating for it instead of
  one carried over from pool-D.

## Not doing

- A multi-threaded search. The rating work is single-core, so it would measure
  nothing. Worth revisiting only for multi-core lists or tournaments.
- Releasing anything trained on outside data until its licence is settled.
