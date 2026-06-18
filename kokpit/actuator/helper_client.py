from kokpit.actuator.levers import run_argv


def run_helper(verb_args: list[str], runner=run_argv) -> str:
    return runner(["pkexec", "kokpit-actl-helper", *verb_args])
