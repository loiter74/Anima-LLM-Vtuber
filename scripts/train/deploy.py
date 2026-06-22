#!/usr/bin/env python3
"""Deploy trained model to Anima.

Steps:
1. Locate .pth and .index from RVC WebUI training output
2. Verify they exist
3. Update config/singing.yaml with new model name and params
4. Print deployment summary
"""
import shutil
from pathlib import Path

import yaml
from loguru import logger


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    char_name = config["character"]["name"]
    rvc_path = Path(config["anima"]["rvc_path"])
    singing_config_path = Path(config["anima"]["config_path"])

    # Source files (from RVC WebUI training output)
    src_pth = rvc_path / config["anima"]["weights_subdir"] / f"{char_name}.pth"
    src_index = rvc_path / config["anima"]["index_subdir"] / f"{char_name}.index"

    if not src_pth.exists():
        logger.error(f"Model not found: {src_pth}")
        logger.info("Did you train the model? Expected in RVC weights/ directory.")
        logger.info("After RVC WebUI training, the model is automatically saved there.")
        return

    logger.info(f"Model found: {src_pth}")
    if src_index.exists():
        logger.info(f"Index found: {src_index}")
    else:
        logger.warning("Index not found — will skip index in config")

    # Update config/singing.yaml
    if singing_config_path.exists():
        with open(singing_config_path, encoding="utf-8") as f:
            singing_cfg = yaml.safe_load(f) or {}

        if "singing" not in singing_cfg:
            singing_cfg["singing"] = {}
        if "rvc" not in singing_cfg["singing"]:
            singing_cfg["singing"]["rvc"] = {}

        rvc_cfg = singing_cfg["singing"]["rvc"]
        rvc_cfg["model_name"] = f"{char_name}.pth"
        if src_index.exists():
            rvc_cfg["index_path"] = f"logs/{char_name}.index"
        rvc_cfg["f0_method"] = config["rvc"]["f0_method"]
        # Keep existing params if they're not in our config
        rvc_cfg.setdefault("f0_up_key", 0)
        rvc_cfg.setdefault("index_rate", 0.75)
        rvc_cfg.setdefault("filter_radius", 3)
        rvc_cfg.setdefault("rms_mix_rate", 0.25)
        rvc_cfg.setdefault("protect", 0.33)

        with open(singing_config_path, "w", encoding="utf-8") as f:
            yaml.dump(singing_cfg, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"Updated {singing_config_path}")
    else:
        logger.warning(f"singing.yaml not found at {singing_config_path}")

    # Verify
    logger.info("=" * 50)
    logger.info("✅ Deployment complete!")
    logger.info(f"   Model: {char_name}.pth")
    logger.info(f"   Index: {char_name}.index")
    logger.info(f"   Config: {singing_config_path}")
    logger.info("=" * 50)
    logger.info("Next steps:")
    logger.info("   1. Test inference via RVC WebUI or Anima singing pipeline")
    logger.info("   2. For Anima: send a Bilibili URL through the singing module")
    logger.info("   3. Adjust f0_up_key if the pitch doesn't match the target character")


if __name__ == "__main__":
    main()
