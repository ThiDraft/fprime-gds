#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

"""
Parses the given CLI command for the F' GDS, and then executes the correct
command with the user-provided arguments on the GDS
"""

import abc
import argparse
from copy import deepcopy
import os
import sys
import pkg_resources
from typing import Callable, List, Union

import argcomplete

# NOTE: These modules are now only lazily loaded below as needed, due to slow
# performance when importing them
# import fprime_gds.common.gds_cli.channels as channels
# import fprime_gds.common.gds_cli.command_send as command_send
# import fprime_gds.common.gds_cli.events as events
# from fprime_gds.common.pipeline.dictionaries import Dictionaries
from fprime_gds.executables.cli import (
    StandardPipelineParser,
    SearchArgumentsParser,
    RetrievalArgumentsParser,
)


def add_connection_arguments(parser: argparse.ArgumentParser):
    """
    Adds the arguments needed to properly connect to the API, which the user may
    want to specify
    """

    pipeline_parser_args = StandardPipelineParser().get_arguments()
    pipeline_parser = parser.add_argument_group("GDS Options")

    for arg, kwargs in pipeline_parser_args.items():
        pipeline_parser.add_argument(*arg, **kwargs)


def add_retrieval_arguments(
    parser: argparse.ArgumentParser, command_name: str, exclude: List[str] = None
):
    """
    Adds the arguments that affect how a commands retrieves a message generated by the GDS or F' instance
    """
    # Work-around to using a mutable default argument
    if exclude is None:
        exclude = []

    retrieval_parser_args = RetrievalArgumentsParser(command_name).get_arguments()
    retrieval_parser = parser.add_argument_group("Retrieval Options")

    for arg, kwargs in retrieval_parser_args.items():
        if arg[0] not in exclude:
            retrieval_parser.add_argument(*arg, **kwargs)


def add_search_arguments(parser: argparse.ArgumentParser, command_name: str):
    """
    Adds all the arguments relevant to searching/filtering certain messages
    used by the Channels/Commands/Events commands with the given name used in
    the help text, due to the similarity of each of these commands
    """

    search_parser_args = SearchArgumentsParser(command_name).get_arguments()
    search_parser = parser.add_argument_group("Search/Filtering Options")

    for arg, kwargs in search_parser_args.items():
        search_parser.add_argument(*arg, **kwargs)


def get_dictionary_path(current_args: argparse.Namespace) -> Union[str, None]:
    """
    Returns the current project dictionary, either one provided by the user
    or the first one found in the current working directory. Raises an
    exception if neither one is found.
    """
    args = deepcopy(current_args)
    if not hasattr(args, "dictionary"):
        args.dictionary = None
    args.deploy = os.getcwd()
    args.config = None
    return args.dictionary


def add_valid_dictionary(args: argparse.Namespace) -> argparse.Namespace:
    """
    Takes in the given parsed arguments and, if no F' dictionary has been given,
    attempt to search for one in the current working directory. Throw an error
    if none can be found OR if the given dictionary is invalid.
    """
    args.dictionary = get_dictionary_path(args)
    return args


class CliSubparserInjectorBase(abc.ABC):
    """
    An abstract class for CLI commands to implement; provides methods for
    injecting a new parser for this command into a parent parser
    """

    @classmethod
    def inject_subparser(cls, parent_parser: argparse.ArgumentParser):
        """
        Adds this command as a sub-command to an existing parser, so that it
        can be passed in as an argument (similar to git's CLI tool)
        """
        command_parser = cls.create_subparser(parent_parser)
        cls.add_arguments(command_parser)
        command_parser.set_defaults(func=cls.command_func, validate=cls.validate_args)

    @classmethod
    @abc.abstractmethod
    def create_subparser(
        cls, parent_parser: argparse.ArgumentParser
    ) -> argparse.ArgumentParser:
        """
        Creates the parser for this command as a subparser of the given one,
        and then returns it
        """

    @classmethod
    @abc.abstractmethod
    def add_arguments(cls, parser: argparse.ArgumentParser):
        """
        Add all the required and optional arguments for this command to the
        given parser
        """

    @classmethod
    def validate_args(cls, parser: argparse.ArgumentParser, args: argparse.Namespace):
        """
        Validates the parsed arguments for this parser; if any are incorrect or
        missing, try to set them automatically if possible and error if this is
        not possible

        By default, tries to set the project dictionary
        """
        try:
            args = add_valid_dictionary(args)
        except ValueError:
            parser.error("No valid project dictionary found")
        return args

    @classmethod
    @abc.abstractmethod
    def command_func(cls, parsed_args, **kwargs) -> Callable:
        """
        Executes the appropriate function when this command is called
        """


class ChannelsSubparserInjector(CliSubparserInjectorBase):
    """
    A parser for the "channels" CLI command, which lets users retrieve
    information about recent telemetry data from an F' instance
    """

    @classmethod
    def create_subparser(cls, parent_parser: argparse.ArgumentParser):
        """
        Creates the channels sub-command as a subparser, and then returns it
        """
        return parent_parser.add_parser(
            "channels",
            description="print out new telemetry data that has been received from the F Prime instance, sorted by timestamp",
        )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser):
        """
        Add all the required and optional arguments for this command to the
        given parser
        """
        add_connection_arguments(parser)
        add_search_arguments(parser, "channels")
        add_retrieval_arguments(parser, "channels")

    @classmethod
    def command_func(cls, parsed_args, **kwargs):
        """
        Executes the appropriate function when "channels" is called
        """
        import fprime_gds.common.gds_cli.channels as channels

        channels.ChannelsCommand.handle_arguments(parsed_args, **kwargs)


class CommandSubparserInjector(CliSubparserInjectorBase):
    """
    A parser for the "command-send" CLI command, which lets users send commands
    from the GDS to a running F' instance and lets retrieve information about
    what commands are available
    """

    @classmethod
    def create_subparser(cls, parent_parser: argparse.ArgumentParser):
        """
        Creates the command-send sub-command as a subparser, and then returns it
        """
        return parent_parser.add_parser(
            "command-send",
            description="sends the given command to the spacecraft via the GDS",
        )

    @staticmethod
    def complete_command_name(
        prefix: str, parsed_args: argparse.Namespace, **kwargs
    ) -> List[str]:
        """
        Returns a list of all command names that could possibly complete the
        given prefix
        """
        # Kwargs arguments required for argcomplete, so suppress warning
        # pylint: disable=unused-argument
        dict_path = ""
        try:
            dict_path = get_dictionary_path(parsed_args)
        except ValueError:
            argcomplete.warn("No dictionary found to get command names from")
            return []

        from fprime_gds.common.pipeline.dictionaries import Dictionaries

        dictionary = Dictionaries()
        dictionary.load_dictionaries(dict_path, None)
        command_names = dictionary.command_name.keys()
        return [name for name in command_names if name.startswith(prefix)]

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser):
        """
        Add all the required and optional arguments for this command to the
        given parser
        """
        add_connection_arguments(parser)
        parser.add_argument(
            "command_name",
            help='the full name of the command you want to execute in "<component>.<name>" form',
            nargs="?",
            metavar="command-name",
        ).completer = cls.complete_command_name
        # NOTE: Type set to string because we don't know the type beforehand
        parser.add_argument(
            "--arguments",
            nargs="*",
            type=str,
            default=[],
            help="provide a space-separated set of arguments to the command being sent",
        )
        add_search_arguments(parser, "commands")
        add_retrieval_arguments(parser, "commands", exclude=["-t", "--timeout"])

    @classmethod
    def validate_args(cls, parser: argparse.ArgumentParser, args: argparse.Namespace):
        """
        Validates the parsed arguments for command_send; if any are incorrect or
        missing, try to set them automatically if possible and error if this is
        not possible
        """
        if not (args.command_name or args.is_printing_list):
            parser.error("One of command-name or --list is required")

        args = super().validate_args(parser, args)
        return args

    @classmethod
    def command_func(cls, parsed_args, **kwargs):
        """
        Executes the appropriate function when "command_send" is called
        """
        import fprime_gds.common.gds_cli.command_send as command_send

        command_send.CommandSendCommand.handle_arguments(parsed_args, **kwargs)


class EventsSubparserInjector(CliSubparserInjectorBase):
    """
    A parser for the "events" CLI command, which lets users retrieve
    information about recent events logged on an F' instance
    """

    @classmethod
    def create_subparser(cls, parent_parser: argparse.ArgumentParser):
        """
        Creates the events sub-command as a subparser, and then returns it
        """
        return parent_parser.add_parser(
            "events",
            description="print out new events that have occurred on the F Prime instance, sorted by timestamp",
        )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser):
        """
        Add all the required and optional arguments for this command to the
        given parser
        """
        add_connection_arguments(parser)
        add_search_arguments(parser, "events")
        add_retrieval_arguments(parser, "events")

    @classmethod
    def command_func(cls, parsed_args, **kwargs):
        """
        Executes the appropriate function when "events_parser" is called
        """
        import fprime_gds.common.gds_cli.events as events

        events.EventsCommand.handle_arguments(parsed_args, **kwargs)


def create_parser():
    parser = argparse.ArgumentParser(
        description="provides utilities for interacting with the F' Ground Data System (GDS)"
    )
    fprime_gds_version = pkg_resources.get_distribution("fprime-gds").version
    parser.add_argument("-V", "--version", action="version", version=fprime_gds_version)

    # Add subcommands to the parser
    subparser_root = parser.add_subparsers(dest="func")
    ChannelsSubparserInjector.inject_subparser(subparser_root)
    CommandSubparserInjector.inject_subparser(subparser_root)
    EventsSubparserInjector.inject_subparser(subparser_root)

    return parser


def parse_args(parser: argparse.ArgumentParser, arguments):
    """
    Parses the given arguments and returns the resulting namespace; having this
    separate allows for unit testing if needed
    """
    args = parser.parse_args(arguments)

    if not args.func:
        # no argument provided, so print the help message
        parser.print_help()
        sys.exit()

    args = args.validate(parser, args)

    return args


def main():
    # parse arguments, not including the name of this script
    parser = create_parser()
    argcomplete.autocomplete(parser)
    args_ns = parse_args(parser, sys.argv[1:])

    # Call the selected command function with the args provided
    function = args_ns.func
    function(args_ns)


if __name__ == "__main__":
    main()
