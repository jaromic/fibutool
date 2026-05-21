FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace

# copy only requirements first (important!)
COPY requirements.txt .

# install Python deps
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install build && python -m build --wheel && pip install dist/*.whl \
    && find /workspace -maxdepth 1 -name "*.py" -delete \
    && rm -rf dist/ build/
CMD ["bash"]