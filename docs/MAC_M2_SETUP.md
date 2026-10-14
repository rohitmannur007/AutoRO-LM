# Mac M2 setup

Verified on this machine on 2026-10-13: macOS 26.6.2, arm64, Python 3.11.8, Node 24.11.0, npm 11.6.1. Docker and Ollama were present and are optional.

Commands assume the repository folder is `Auto Royal M`. Quote the path because of the space.

```bash
cd "/Users/rohitmannur/Desktop/Auto Royal M"
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -U pip
python -m pip install -e "./backend[dev]"
cd frontend
npm install
cd ..
chmod +x scripts/*.sh
./scripts/doctor.sh
./scripts/dev.sh
```

- UI: http://127.0.0.1:5173
- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health

The first API start creates `backend/data/runtime/autoro.sqlite3` and loads DEMO fixtures. No API key, GPU, Docker, or model download is required.

If port 8000 is already used by another app, start the API on another port and point the UI at it:

```bash
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
# in another terminal
cd frontend && AUTORO_API_PROXY=http://127.0.0.1:8010 npm run dev -- --host 127.0.0.1 --port 5173
AUTORO_API=http://127.0.0.1:8010 ./scripts/acceptance.sh
```

`lsof -nP -iTCP:8000 -sTCP:LISTEN` shows the current listener. Do not stop an unrelated process just to free the port.

## Optional MongoDB

```bash
docker compose up -d mongo
```

Then in `.env` (copy from `.env.example`):

```text
AUTORO_DATABASE_URL=mongodb://localhost:27017
```

Install the driver only if you use it:

```bash
python -m pip install -e "./backend[mongo]"
```

If the URL is set and MongoDB does not answer, the API falls back to SQLite and the health payload sets `database.fallback` to true with the reason. It does not claim MongoDB is connected.

## Optional Ollama

This machine had `llama3.2:1b`. The demo provider does not call it.

```bash
ollama serve
ollama pull llama3.2:1b
```

Set `AUTORO_PROVIDER=ollama` and `AUTORO_OLLAMA_MODEL=llama3.2:1b`. If the server or model is missing, `/api/v1/extract` returns HTTP 503.

## Optional MLX fine-tune

```bash
python -m pip install mlx-lm
backend/.venv/bin/python backend/scripts/mlx_finetune.py
```

With no arguments the script exits 2 until `mlx-lm` imports. After it imports, build a train file from the Training screen or:

```bash
# prints the mlx_lm.lora command and does not train
backend/.venv/bin/python backend/scripts/mlx_finetune.py --dry-run --data backend/data/runtime/training/share-0 --adapter /tmp/autoro-adapter
```

A real launch is `mlx_finetune.py --data <train dir> --adapter <adapter dir>`. The API does the same thing when the confirmation text is `TRAIN_MLX`. The process fails if mlx-lm or the model is missing. It does not write a successful manifest in that case. Use only train-split JSONL. The gold test set is excluded by the dataset builder.

PEFT/QLoRA with bitsandbytes is a CUDA or cloud environment. Do not expect that stack to run on an M2.

## Tests

```bash
./scripts/test.sh
```

## Common errors

- `python3` older than 3.11: install 3.11 or 3.12 with pyenv. The project does not require 3.13.
- `npm` not found: install Node with nvm. The frontend was installed with Node 24.
- Apple Silicon wheels: pip selected `macosx_*_arm64` wheels for numpy and scikit-learn in this environment. Do not install a CUDA torch build for the demo.
- Hosted provider: set `AUTORO_OPENAI_COMPAT_BASE_URL`, `AUTORO_OPENAI_COMPAT_API_KEY`, and `AUTORO_OPENAI_COMPAT_MODEL` in `.env`. The key is not returned by the API. Leave them empty to stay offline.
