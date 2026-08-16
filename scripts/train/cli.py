#!/usr/bin/env python3
"""Anima Train CLI — 一键训练 RVC v2 歌声模型.

一键完成：数据预处理 → 特征提取 → 模型训练 → 建索引 → 部署到 Anima

Usage:
    # 标准训练（使用现有数据或下载）
    python -m scripts.train.cli --character shige_utage

    # 指定数据目录
    python -m scripts.train.cli --character shige_utage --data ./data/training/ready

    # 仅预处理（不训练）
    python -m scripts.train.cli --character shige_utage --preprocess-only

    # 仅部署已有模型
    python -m scripts.train.cli --character shige_utage --deploy-only
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import yaml

# ── Paths ────────────────────────────────────────────────────────

RVC_ROOT = Path("C:/Users/30262/RVC20240604Nvidia")
PYTHON = sys.executable
SCRIPT_DIR = Path(__file__).parent
NOW_DIR = str(RVC_ROOT)


def load_config() -> dict:
    config_path = SCRIPT_DIR / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_step(step_name: str, cmd: list[str], cwd: str = NOW_DIR) -> None:
    """Run a CLI step with logging."""
    print(f"\n{'=' * 60}")
    print(f"  [{step_name}]")
    print(f"  {' '.join(cmd)}")
    print(f"{'=' * 60}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"  [!] Return code: {result.returncode}")
        if result.stderr:
            print(f"  Error: {result.stderr[-500:]}")
    else:
        print(f"  Done in {elapsed:.1f}s")
    if result.stdout and "Error" not in result.stdout[-200:]:
        for line in result.stdout.strip().split("\n")[-3:]:
            if line.strip():
                print(f"  {line}")
    print()


# ── Steps ────────────────────────────────────────────────────────


def step_preprocess_data() -> None:
    """Run data prep: slice → normalize → pitch augment → split."""
    run_step("Prepare Data", [PYTHON, str(SCRIPT_DIR / "prepare_data.py")], cwd=str(SCRIPT_DIR))


def step_rvc_preprocess(exp_dir: str, dataset_dir: str, sr: str, version: str) -> None:
    """Step 1: RVC audio preprocessing (resample + slice)."""
    cmd = [
        PYTHON,
        "infer/modules/train/preprocess.py",
        dataset_dir,
        sr,
        "4",  # n_p (CPU cores for preprocessing)
        f"{RVC_ROOT}/logs/{exp_dir}",
        version,
    ]
    run_step("RVC: Audio Preprocessing", cmd)


def step_rvc_extract_f0(exp_dir: str, f0_method: str) -> None:
    """Step 2: Extract F0 using rmvpe."""
    cmd = [
        PYTHON,
        "infer/modules/train/extract/extract_f0_rmvpe.py",
        "4",  # n_p
        "0",  # gpu
        "1",  # f0_flag
        f"{RVC_ROOT}/logs/{exp_dir}",
        "4",  # num_processes
    ]
    run_step("RVC: F0 Extraction (rmvpe)", cmd)


def step_rvc_extract_features(exp_dir: str, version: str) -> None:
    """Step 3: Extract HuBERT/ContentVec features."""
    if version == "v2":
        cmd = [
            PYTHON,
            "infer/modules/train/extract_feature_print.py",
            "4",  # n_p
            "0",  # gpu
            f"{RVC_ROOT}/logs/{exp_dir}",
            version,
        ]
    else:
        cmd = [
            PYTHON,
            "infer/modules/train/extract_feature_print.py",
            "4",  # n_p
            "0",  # gpu
            f"{RVC_ROOT}/logs/{exp_dir}",
            "0",  # v1 needs 0/1 param
        ]
    run_step("RVC: Feature Extraction (ContentVec)", cmd)


def step_rvc_train(
    exp_dir: str,
    sr: str,
    f0: int,
    batch_size: int,
    total_epoch: int,
    save_epoch: int,
    version: str,
    pretrained_g: str = "",
    pretrained_d: str = "",
    gpu: str = "0",
) -> None:
    """Step 4: Train the RVC model."""
    cmd = [
        PYTHON,
        "infer/modules/train/train.py",
        "-e",
        exp_dir,
        "-sr",
        sr,
        "-f0",
        str(f0),
        "-bs",
        str(batch_size),
        "-g",
        gpu,
        "-te",
        str(total_epoch),
        "-se",
        str(save_epoch),
        "-l",
        "1",  # save latest
        "-c",
        "0",  # cache in GPU
        "-sw",
        "1",  # save every weight
        "-v",
        version,
    ]
    if pretrained_g:
        cmd.extend(["-pg", pretrained_g])
    if pretrained_d:
        cmd.extend(["-pd", pretrained_d])
    run_step("RVC: Model Training", cmd)


def step_rvc_build_index(exp_dir: str, version: str) -> None:
    """Step 5: Build FAISS feature index."""
    cmd = [
        PYTHON,
        "tools/infer/train-index-v2.py",
        "-e",
        exp_dir,
        "-v",
        version,
    ]
    run_step("RVC: Build FAISS Index", cmd)


def step_deploy() -> None:
    """Step 6: Deploy model to Anima."""
    run_step(
        "Deploy to Anima",
        [PYTHON, str(SCRIPT_DIR / "deploy.py")],
        cwd=str(SCRIPT_DIR),
    )


# ── CLI ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Anima Train — 一键训练 RVC v2 歌声模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.train.cli --character shige_utage
  python -m scripts.train.cli --character shige_utage --preprocess-only
  python -m scripts.train.cli --character shige_utage --epochs 500
  python -m scripts.train.cli --character shige_utage --deploy-only
        """,
    )
    parser.add_argument(
        "--character",
        "-c",
        default=None,
        help="Character name (from config.yaml). Default: from config",
    )
    parser.add_argument(
        "--data",
        "-d",
        default=None,
        help="Path to training data directory. Default: data/training/ready",
    )
    parser.add_argument(
        "--epochs", "-e", type=int, default=None, help="Training epochs (default: from config: 300)"
    )
    parser.add_argument(
        "--batch-size", "-b", type=int, default=None, help="Batch size (default: from config: 16)"
    )
    parser.add_argument("--sr", default=None, help="Sample rate (default: from config: 48000)")
    parser.add_argument("--gpu", default="0", help="GPU ID (default: 0)")
    parser.add_argument(
        "--f0-method", default="rmvpe", help="F0 extraction method (default: rmvpe)"
    )
    parser.add_argument(
        "--pretrained-g",
        default=None,
        help="Pretrained generator path (default: auto from sr+version)",
    )
    parser.add_argument(
        "--pretrained-d",
        default=None,
        help="Pretrained discriminator path (default: auto from sr+version)",
    )
    parser.add_argument(
        "--skip-prep",
        action="store_true",
        help="Skip data preparation (use existing processed data)",
    )
    parser.add_argument(
        "--preprocess-only",
        action="store_true",
        help="Only run RVC preprocessing + feature extraction, no training",
    )
    parser.add_argument(
        "--deploy-only", action="store_true", help="Only deploy existing model (no training)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")

    args = parser.parse_args()
    config = load_config()

    # Resolve params
    char_name = args.character or config["character"]["name"]
    sr = args.sr or str(config["rvc"]["sample_rate"])
    version = config["rvc"].get("version", "v2")
    total_epoch = args.epochs or config["rvc"]["epochs"]
    batch_size = args.batch_size or config["rvc"]["batch_size"]
    f0 = 1  # Always enable F0 for singing
    dataset_dir = args.data or str(Path(config["data"]["processed_dir"]).parent / "ready")

    # Auto-detect pretrained paths
    pg = (
        args.pretrained_g or f"assets/pretrained_v2/f0G{sr}.pth"
        if version == "v2"
        else f"assets/pretrained/f0G{sr}.pth"
    )
    pd = (
        args.pretrained_d or f"assets/pretrained_v2/f0D{sr}.pth"
        if version == "v2"
        else f"assets/pretrained/f0D{sr}.pth"
    )

    # Verify paths
    if not args.deploy_only:
        pg_path = RVC_ROOT / pg
        pd_path = RVC_ROOT / pd
        if not pg_path.exists():
            print(f"[WARN] Pretrained G not found: {pg_path}")
            print("       Download from: https://huggingface.co/lj1995/VoiceConversionWebUI")
            pg = ""
        if not pd_path.exists():
            print(f"[WARN] Pretrained D not found: {pd_path}")
            pd = ""

    print(f"\n{'#' * 60}")
    print(f"  Anima Train — {char_name}")
    print(f"  SR: {sr}  |  Version: {version}  |  Epochs: {total_epoch}  |  Batch: {batch_size}")
    print(f"  Data: {dataset_dir}")
    print(f"{'#' * 60}\n")

    # ── Execute ──

    if args.deploy_only:
        step_deploy()
        return

    if args.dry_run:
        print("Dry-run mode. Commands would be:")
        return

    # Step A: Data preparation (02-05)
    if not args.skip_prep:
        step_preprocess_data()
    else:
        print("[SKIP] Skipping data preparation (--skip-prep)")

    # Step B: RVC Preprocessing
    step_rvc_preprocess(char_name, dataset_dir, sr, version)

    # Step C: F0 Extraction
    step_rvc_extract_f0(char_name, args.f0_method)

    # Step D: Feature Extraction
    step_rvc_extract_features(char_name, version)

    if args.preprocess_only:
        print("[DONE] Preprocessing complete. Ready for training.")
        print("       Run without --preprocess-only to train.")
        return

    # Step E: Training
    step_rvc_train(
        exp_dir=char_name,
        sr=sr,
        f0=f0,
        batch_size=batch_size,
        total_epoch=total_epoch,
        save_epoch=50,
        version=version,
        pretrained_g=pg if pg else "",
        pretrained_d=pd if pd else "",
        gpu=args.gpu,
    )

    # Step F: Build Index
    step_rvc_build_index(char_name, version)

    # Step G: Deploy to Anima
    step_deploy()

    print(f"\n{'=' * 60}")
    print(f"  [DONE] Training complete for {char_name}!")
    print(f"  Model: {RVC_ROOT}/weights/{char_name}.pth")
    print(f"  Index: {RVC_ROOT}/logs/{char_name}.index")
    print("  Anima config: config/singing.yaml")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
