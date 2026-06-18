from kokpit.ui.widgets.proposal_bar import ProposalBar


def test_confirm_emits_id(qapp):
    bar = ProposalBar()
    seen = []
    bar.confirmed.connect(seen.append)
    bar.show_proposal("prop-7", "Ograniczyć moc GPU?")
    bar._confirm_btn.click()
    assert seen == ["prop-7"]


def test_command_entered_emits_text(qapp):
    bar = ProposalBar()
    seen = []
    bar.commandEntered.connect(seen.append)
    bar._cmd.setText("cicho na 20 min")
    bar._cmd.returnPressed.emit()
    assert seen == ["cicho na 20 min"]
