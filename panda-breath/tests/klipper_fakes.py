# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Just enough of Klipper to load the panda_breath modules, matched to Snapmaker's u1-klipper."""

import functools
import importlib
import operator
import queue

MISSING = object()
REACTOR_START_TIME = 100.
# Klipper's gcmd.get() limit keywords, the test each one makes, and the error text it raises.
GCODE_LIMIT_CHECKS = (
    ("minval", operator.lt, "must have minimum of"),
    ("maxval", operator.gt, "must have maximum of"),
    ("above", operator.le, "must be above"),
)


class CommandError(Exception):
    pass


class ConfigError(Exception):
    pass


class FakeConfig:
    def __init__(self, printer, section_name, section_options):
        self.printer = printer
        self.section_name = section_name
        self.section_options = section_options
        self.error = ConfigError

    def get_printer(self):
        return self.printer

    def get_name(self):
        return self.section_name

    def getsection(self, section_name):
        return FakeConfig(self.printer, section_name, self.printer.sections.get(section_name, {}))

    def get(self, option, default=MISSING):
        if option in self.section_options:
            return self.section_options[option]
        if default is MISSING:
            raise ConfigError(
                f"Option '{option}' in section '{self.section_name}' must be specified")
        return default

    def getint(self, option, default=MISSING):
        return int(self.get(option, default))

    def getfloat(self, option, default=MISSING, minval=None, above=None):
        option_value = float(self.get(option, default))
        if minval is not None and option_value < minval:
            raise ConfigError(f"Option '{option}' must have minimum of {minval}")
        if above is not None and option_value <= above:
            raise ConfigError(f"Option '{option}' must be above {above}")
        return option_value

    def get_prefix_sections(self, prefix):
        return [
            self.getsection(section_name) for section_name in self.printer.sections
            if section_name.startswith(prefix)
        ]


class FakeTimer:
    def __init__(self, callback, waketime):
        self.callback = callback
        self.waketime = waketime


class FakeReactor:
    """A reactor on a simulated clock: time only moves when a test or a wait pauses it."""

    NOW = 0.
    NEVER = 9999999999999999.

    def __init__(self):
        self.clock = REACTOR_START_TIME
        self.timers = []
        self.async_callbacks = queue.Queue()

    def register_async_callback(self, callback, waketime=NOW):
        """Called from another thread; the next pause runs it, as Klipper's reactor does."""
        self.async_callbacks.put_nowait((callback, waketime))

    def _take_async_callbacks(self):
        while not self.async_callbacks.empty():
            callback, waketime = self.async_callbacks.get_nowait()
            self.register_timer(
                functools.partial(run_async_callback, callback, self.NEVER), waketime)

    def monotonic(self):
        return self.clock

    def register_timer(self, callback, waketime=NEVER):
        timer = FakeTimer(callback, waketime)
        self.timers.append(timer)
        return timer

    def update_timer(self, timer, waketime):
        timer.waketime = waketime

    def pause(self, waketime):
        """Run every timer that falls due before waketime, in time order, like Klipper's reactor."""
        self._take_async_callbacks()
        due_timer = self._next_due_timer(waketime)
        while due_timer is not None:
            self.clock = max(self.clock, due_timer.waketime)
            due_timer.waketime = due_timer.callback(self.clock)
            due_timer = self._next_due_timer(waketime)
        self.clock = max(self.clock, waketime)
        return self.clock

    def advance(self, seconds):
        return self.pause(self.clock + seconds)

    def call_at(self, waketime, action):
        """Run action once at waketime on the reactor, as a device event would arrive."""
        self.register_timer(functools.partial(run_once, action, self.NEVER), waketime)

    def _next_due_timer(self, waketime):
        due_timers = [timer for timer in self.timers if timer.waketime <= waketime]
        return min(due_timers, key=operator.attrgetter("waketime"), default=None)


def run_once(action, never, eventtime):
    action()
    return never


def run_async_callback(callback, never, eventtime):
    callback(eventtime)
    return never


def broken_limit_text(parsed_value, limits):
    """Return Klipper's error text for the first limit parsed_value breaks, or None."""
    return next((
        f"{error_text} {limits[limit_name]}"
        for limit_name, breaks_limit, error_text in GCODE_LIMIT_CHECKS
        if limit_name in limits and breaks_limit(parsed_value, limits[limit_name])
    ), None)


def ignore_print_time(print_time):
    return None


class FakeGCodeCommand:
    def __init__(self, gcode, commandline, params):
        self.gcode = gcode
        self.commandline = commandline
        self.params = params
        self.error = CommandError

    def get(self, name, default=MISSING, parser=str, **limits):
        raw_value = self.params.get(name)
        if raw_value is None:
            return self._default_for_missing(name, default)
        parsed_value = parser(raw_value)
        broken_limit = broken_limit_text(parsed_value, limits)
        if broken_limit:
            raise CommandError(f"Error on '{self.commandline}': {name} {broken_limit}")
        return parsed_value

    def _default_for_missing(self, name, default):
        if default is MISSING:
            raise CommandError(f"Error on '{self.commandline}': missing {name}")
        return default

    def get_int(self, name, default=MISSING, **limits):
        return self.get(name, default, parser=int, **limits)

    def get_float(self, name, default=MISSING, **limits):
        return self.get(name, default, parser=float, **limits)

    def respond_info(self, message):
        self.gcode.respond_info(message)


def parse_commandline(commandline):
    """Split "M141 S40" or "PANDA_BREATH_AUTO ENABLE=1" into a command name and its parameters."""
    command_name, *words = commandline.split()
    if "=" in commandline:
        return command_name, dict(word.split("=", 1) for word in words)
    return command_name, {word[0]: word[1:] for word in words}


class FakeGCode:
    def __init__(self):
        self.ready_gcode_handlers = {}
        self.gcode_help = {}
        self.responses = []

    def register_command(self, cmd, func, when_not_ready=False, desc=None):
        if func is None:
            return self.ready_gcode_handlers.pop(cmd, None)
        if cmd in self.ready_gcode_handlers:
            raise ConfigError(f"gcode command {cmd} already registered")
        self.ready_gcode_handlers[cmd] = func
        if desc is not None:
            self.gcode_help[cmd] = desc
        return None

    def run(self, commandline):
        command_name, params = parse_commandline(commandline)
        handler = self.ready_gcode_handlers[command_name]
        handler(FakeGCodeCommand(self, commandline, params))

    def respond_raw(self, message):
        self.responses.append(message)

    def respond_info(self, message):
        self.responses.append("// " + message)


class FakeHeater:
    """A watermark heater_generic, as Klipper's heaters.Heater behaves for it."""

    def __init__(self, name, sensor, heater_options):
        self.name = name
        self.min_temp = float(heater_options["min_temp"])
        self.max_temp = float(heater_options["max_temp"])
        self.max_delta = float(heater_options["max_delta"])
        self.smoothed_temp = 0.
        self.target_temp = 0.
        sensor.setup_callback(self.temperature_callback)

    def temperature_callback(self, read_time, temp):
        self.smoothed_temp = temp

    def get_name(self):
        return self.name

    def set_temp(self, degrees):
        if degrees and (degrees < self.min_temp or degrees > self.max_temp):
            raise CommandError(
                f"Requested temperature ({degrees:.1f}) out of range"
                f" ({self.min_temp:.1f}:{self.max_temp:.1f})")
        self.target_temp = degrees

    def get_temp(self, eventtime):
        return self.smoothed_temp, self.target_temp

    def check_busy(self, eventtime):
        return self.smoothed_temp < self.target_temp - self.max_delta


class FakeHeaters:
    def __init__(self, printer):
        self.printer = printer
        self.sensor_factories = {}
        self.heaters = {}

    def add_sensor_factory(self, sensor_type, sensor_factory):
        self.sensor_factories[sensor_type] = sensor_factory

    def setup_heater(self, heater_name, heater_options):
        sensor_factory = self.sensor_factories[heater_options["sensor_type"]]
        sensor = sensor_factory(FakeConfig(self.printer, heater_name, heater_options))
        self.heaters[heater_name] = FakeHeater(heater_name, sensor, heater_options)
        return self.heaters[heater_name]

    def lookup_heater(self, heater_name):
        if heater_name not in self.heaters:
            raise ConfigError(f"Unknown heater '{heater_name}'")
        return self.heaters[heater_name]

    def set_temperature(self, heater, temp, wait=False):
        self.printer.lookup_object("toolhead").register_lookahead_callback(ignore_print_time)
        heater.set_temp(temp)


class FakeToolhead:
    def register_lookahead_callback(self, callback):
        callback(0.)

    def get_last_move_time(self):
        return 0.


class FakePins:
    def __init__(self):
        self.chips = {}

    def register_chip(self, chip_name, chip):
        self.chips[chip_name] = chip


class FakePrinter:
    def __init__(self, sections):
        self.sections = sections
        self.reactor = FakeReactor()
        self.event_handlers = {}
        self.command_error = CommandError
        self.config_error = ConfigError
        self.objects = {
            "gcode": FakeGCode(),
            "heaters": FakeHeaters(self),
            "pins": FakePins(),
            "toolhead": FakeToolhead(),
        }

    def get_reactor(self):
        return self.reactor

    def get_start_args(self):
        return {}

    def is_shutdown(self):
        return False

    def lookup_object(self, name, default=MISSING):
        if name in self.objects:
            return self.objects[name]
        if default is MISSING:
            raise ConfigError(f"Unknown config object '{name}'")
        return default

    def load_object(self, config, section):
        if section not in self.objects:
            extras_module = importlib.import_module("extras." + section)
            self.objects[section] = extras_module.load_config(config.getsection(section))
        return self.objects[section]

    def register_event_handler(self, event, callback):
        self.event_handlers.setdefault(event, []).append(callback)

    def send_event(self, event):
        for callback in self.event_handlers.get(event, []):
            callback()
