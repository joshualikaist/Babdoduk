"""validate_content.py --only: each job validates the families it is about to publish, so a
problem in one family (for example one expired free-food event) cannot block another family."""
import pytest

import validate_content


def test_only_validates_the_families_being_published(tmp_path, monkeypatch, capsys):
    broken = tmp_path / "data" / "ggongbab"
    broken.mkdir(parents=True)
    (broken / "latest.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(validate_content, "ROOT", tmp_path)
    validate_content.main(["--only", "kaist-menu", "magazine"])
    assert "content validation ok (kaist-menu, magazine)" in capsys.readouterr().out
    for argv in (["--only", "ggongbab"], []):              # the broken family, and all by default
        with pytest.raises(SystemExit) as stopped:
            validate_content.main(argv)
        assert stopped.value.code == 1
    assert "ggongbab JSON invalid" in capsys.readouterr().out


def test_unknown_families_are_refused(capsys):
    with pytest.raises(SystemExit) as stopped:
        validate_content.main(["--only", "everything"])
    assert stopped.value.code == 2
