"""Render alertmanager.yaml.tftpl for an offline check (plan 10.4a). No AWS.

  render_alertmanager.py OUT_DIR [--topic-arn ARN]

Writes OUT_DIR/alertmanager.yml (the `alertmanager_config` text, with the
template reference changed to a file path) and OUT_DIR/cerberus_sns (the
template file), so `amtool check-config` can read them. The default ARN is a
dummy: the repo holds no account ID, and Terraform builds the real one.
"""

import argparse
import sys
from pathlib import Path

import yaml

TEMPLATE = Path(__file__).resolve().parent / "alertmanager.yaml.tftpl"
DUMMY_ARN = "arn:aws:sns:us-east-1:dummy-account:cerberus-pipeline-alerts"


def render(topic_arn: str, template: Path = TEMPLATE) -> dict:
    """The parsed definition: {"alertmanager_config": str, "template_files": {name: str}}."""
    text = template.read_text(encoding="utf-8").replace("${topic_arn}", topic_arn)
    if "${" in text or "%{" in text:
        raise ValueError("the template has a variable other than topic_arn")
    return yaml.safe_load(text)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out_dir", type=Path)
    p.add_argument("--topic-arn", default=DUMMY_ARN)
    args = p.parse_args(argv)
    definition = render(args.topic_arn)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load(definition["alertmanager_config"])
    files = definition["template_files"]
    # AMP names a template by its template_files key; amtool needs a path.
    config["templates"] = [str(args.out_dir / name) for name in files]
    (args.out_dir / "alertmanager.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    for name, body in files.items():
        (args.out_dir / name).write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
