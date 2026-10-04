set -e
S=C:/Users/Prathik/AppData/Local/Temp/claude/C--Swarms/5b3cb362-197f-4ccc-a976-2d9bb1ddbc1a/scratchpad/b5b
D=/c/Swarms/data/acquired/terminal-bench-2-leaderboard/hf_repo
REV=572b2614be2c0cb2527e14f5b1e4026f1072e6c1
export GIT_LFS_SKIP_SMUDGE=1
date
git clone --filter=blob:none --no-checkout --depth 1 --revision=$REV https://huggingface.co/datasets/harborframework/terminal-bench-2-leaderboard "$D"
cd "$D"
git config core.longpaths true
git sparse-checkout init --no-cone
git sparse-checkout set --no-cone --stdin < $S/tb2_sparse_patterns.txt
date; echo CHECKOUT
git checkout $REV 2>&1 | tail -3
date; echo CHECKOUT_DONE
git rev-parse HEAD
