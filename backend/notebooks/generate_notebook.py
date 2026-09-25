#!/usr/bin/env python3
import json
from pathlib import Path

# Create notebook cells
cells = []

# Title
cells.append({
    "cell_type": "markdown",
    "metadata": {},
    "source": ["# TFT Stock Return Prediction\n\n12-month lookback, 1-month horizon prediction model"]
})

# Setup - Install dependencies
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "import subprocess, sys\n",
        "print('Installing dependencies...')\n",
        "packages = ['torch', 'pytorch-forecasting', 'lightning', 'scikit-learn']\n",
        "for pkg in packages:\n",
        "    subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])\n",
        "print('All dependencies installed!')"
    ]
})

# Imports
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "import pandas as pd\n",
        "import numpy as np\n",
        "import torch\n",
        "import warnings\n",
        "from pathlib import Path\n",
        "from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet\n",
        "from pytorch_forecasting.data import GroupNormalizer\n",
        "from pytorch_forecasting.metrics import QuantileLoss\n",
        "from pytorch_lightning import Trainer\n",
        "from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint\n",
        "from torch.utils.data import DataLoader\n",
        "from sklearn.metrics import mean_absolute_error, mean_squared_error\n",
        "\n",
        "warnings.filterwarnings('ignore')\n",
        "torch.manual_seed(42)\n",
        "np.random.seed(42)\n",
        "\n",
        "REPO = Path('../../').resolve()\n",
        "CSV_RAW = REPO / 'data/processed/final/stock_macro_monthly_target.csv'\n",
        "CSV_MODEL = REPO / 'data/processed/final/stock_macro_monthly_model.csv'\n",
        "MODEL_DIR = REPO / 'models/tft'\n",
        "\n",
        "print(f'OK - Imports successful')\n",
        "print(f'GPU available: {torch.cuda.is_available()}')"
    ]
})

# Load & prepare
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "df = pd.read_csv(CSV_RAW)\n",
        "df['date'] = pd.to_datetime(df['date'])\n",
        "df = df.sort_values(['isin', 'date']).reset_index(drop=True)\n",
        "print(f'Loaded: {df.shape[0]} rows, {df[\"isin\"].nunique()} stocks, {df[\"date\"].min()} to {df[\"date\"].max()}')"
    ]
})

# Recompute returns
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "# From monthly_open: (open[t] - open[t-1]) / open[t-1] * 100\n",
        "df['stock_return_1m'] = df.groupby('isin')['monthly_open'].pct_change() * 100\n",
        "df['target_return_1m'] = df.groupby('isin')['stock_return_1m'].shift(-1)\n",
        "df = df.dropna(subset=['stock_return_1m', 'target_return_1m']).reset_index(drop=True)\n",
        "print(f'After dropping NaN: {df.shape[0]} rows')"
    ]
})

# Select features & split
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "features = ['monthly_volume', 'oil_price_usd_bbl', 'oil_return_1m_pct', 'oil_return_12m_pct',\n",
        "            'gold_price_inr_10g', 'gold_return_1m_pct', 'gold_return_12m_pct', 'cpi_index', 'cpi_inflation_yoy_pct', 'stock_return_1m']\n",
        "\n",
        "df = df[['isin', 'symbol', 'date'] + features + ['target_return_1m']].copy()\n",
        "\n",
        "train = df[df['date'] <= pd.Timestamp('2021-08-01')].copy()\n",
        "val = df[(df['date'] > pd.Timestamp('2021-08-01')) & (df['date'] <= pd.Timestamp('2024-02-01'))].copy()\n",
        "test = df[df['date'] > pd.Timestamp('2024-02-01')].copy()\n",
        "\n",
        "print(f'Train: {len(train)}, Val: {len(val)}, Test: {len(test)}')"
    ]
})

# Impute
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "impute = {col: train[col].median() for col in features}\n",
        "for df_split in [train, val, test]:\n",
        "    for col in features:\n",
        "        df_split[col] = df_split[col].fillna(impute[col])\n",
        "print('Imputation complete')"
    ]
})

# TimeSeriesDataSet
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "min_date = df['date'].min()\n",
        "for df_split in [train, val, test]:\n",
        "    df_split['time_idx'] = ((df_split['date'] - min_date) / pd.Timedelta(days=30)).astype(int)\n",
        "\n",
        "isin_map = {isin: i for i, isin in enumerate(df['isin'].unique())}\n",
        "for df_split in [train, val, test]:\n",
        "    df_split['isin_id'] = df_split['isin'].map(isin_map)\n",
        "\n",
        "train_ds = TimeSeriesDataSet(train, time_idx='time_idx', target='target_return_1m', group_ids=['isin_id'],\n",
        "                              min_encoder_length=1, max_encoder_length=12, max_prediction_length=1,\n",
        "                              time_varying_unknown_reals=features, target_normalizer=GroupNormalizer(groups=['isin_id']),\n",
        "                              add_relative_time_idx=True, allow_missing_timesteps=True)\n",
        "val_ds = TimeSeriesDataSet.from_dataset(train_ds, val, predict=False)\n",
        "\n",
        "print(f'Datasets: train={len(train_ds)}, val={len(val_ds)}')"
    ]
})

# DataLoaders
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "train_dl = DataLoader(train_ds, batch_size=64, num_workers=0, shuffle=False)\n",
        "val_dl = DataLoader(val_ds, batch_size=64, num_workers=0, shuffle=False)\n",
        "\n",
        "batch = next(iter(train_dl))\n",
        "print(f'Batch: encoder={batch[\"encoder_data\"].shape}, target={batch[\"target\"].shape}')"
    ]
})

# Train TFT
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "tft = TemporalFusionTransformer.from_dataset(train_ds, learning_rate=0.001, hidden_size=64,\n",
        "                                             attention_head_size=4, hidden_continuous_size=32, dropout=0.1, loss=QuantileLoss())\n",
        "print(f'Model params: {sum(p.numel() for p in tft.parameters()):,}')\n",
        "\n",
        "MODEL_DIR.mkdir(parents=True, exist_ok=True)\n",
        "trainer = Trainer(max_epochs=30, callbacks=[EarlyStopping('val_loss', patience=5),\n",
        "                                             ModelCheckpoint(MODEL_DIR, monitor='val_loss', save_top_k=1)],\n",
        "                  gradient_clip_val=0.1, accelerator='cpu', logger=False)\n",
        "\n",
        "trainer.fit(tft, train_dl, val_dl)\n",
        "print('Training complete')"
    ]
})

# Evaluate
cells.append({
    "cell_type": "code",
    "execution_count": None,
    "metadata": {},
    "outputs": [],
    "source": [
        "test_ds = TimeSeriesDataSet.from_dataset(train_ds, test, predict=False)\n",
        "test_dl = DataLoader(test_ds, batch_size=64, num_workers=0, shuffle=False)\n",
        "\n",
        "tft.eval()\n",
        "preds, actuals = [], []\n",
        "with torch.no_grad():\n",
        "    for batch in test_dl:\n",
        "        preds.extend(tft(batch)[:, 0, 1].cpu().numpy())\n",
        "        actuals.extend(batch['target'].cpu().numpy().flatten())\n",
        "\n",
        "preds, actuals = np.array(preds), np.array(actuals)\n",
        "mae = mean_absolute_error(actuals, preds)\n",
        "rmse = np.sqrt(mean_squared_error(actuals, preds))\n",
        "\n",
        "print(f'Test Results:')\n",
        "print(f'  MAE:  {mae:.4f}%')\n",
        "print(f'  RMSE: {rmse:.4f}%')"
    ]
})

# Build notebook
notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.10.0"}
    },
    "nbformat": 4,
    "nbformat_minor": 4
}

# Save
nb_path = Path("backend/notebooks/train_tft.ipynb")
with open(nb_path, 'w') as f:
    json.dump(notebook, f, indent=1)

# Validate
with open(nb_path) as f:
    json.load(f)

print(f"OK - Created: {nb_path}")
