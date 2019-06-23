from __future__ import annotations

import configparser
import logging
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import List, Callable, Dict, Union, Tuple, Any, Set

LOGGER = logging.getLogger('config_savvy')


class ConfigError(Exception):
    pass


class UndefinedOptionError(ConfigError):
    # when you request an option that has not been
    # defined in the config
    pass


class UnassignedOptionError(ConfigError):
    # when the option's value could not be determined
    # after querying all resolvers, explicit and default value
    pass


class UnassignedResolverError(ConfigError):
    # when trying to resolve an option
    # that does not have an attached resolver
    pass


class NoDirectResolversError(ConfigError):
    # raise when creating a Config class with only ConfigOptions
    # and no resolvers attached
    # if you need to only attach options to a config use the
    # add_options
    pass


class UnsetParameter:
    pass


class Option:

    def __init__(
            self,
            name: str,
            default=UnsetParameter,
            value=UnsetParameter,
            resolved=UnsetParameter,
            processor: Callable = None,
            section: str = UnsetParameter,
            description: str = None,
            resolver: OptionResolver = None
    ):
        super().__init__()
        self.name = name
        self._processor = processor or (lambda x: x)
        self._default = default
        self.section = section
        self._value = value
        self._resolved = resolved
        self.description = description
        self._resolver = resolver
        self.attempts = []

    def __hash__(self):
        return hash((self.name, self.section))

    def __eq__(self, other: Option):
        return self.section == other.section and self.name == other.name

    def __str__(self):
        return self.name

    def bind(self, resolver: OptionResolver):
        self._resolver = resolver
        return self

    def read(self):
        if self._value is not UnsetParameter:
            return self._processor(self._value)

        try:
            self.resolve()
            if self._resolved is not UnsetParameter:
                return self._processor(self._resolved)
        except (UnassignedOptionError, NoDirectResolversError):
            pass

        if self._default is not UnsetParameter:
            return self._processor(self._default)

        raise UnassignedOptionError(f'Could not read value of {self.name}')

    def resolve(self):
        if self._resolver is None:
            raise UnassignedResolverError(f'No resolver for {self.name}')
        self._resolved = self._resolver.read(self, self.section)
        return self


class OptionResolver(ABC):
    @abstractmethod
    def read(self, option: Option) -> Any:
        pass


class Config(OptionResolver):
    def __init__(self, resolvers: List[OptionResolver] = None, options: List[Option] = None, section: str = None):
        # will automatically set the following section to all newly appended ConfigOptions
        self.section = section
        self._options = set()
        self.resolvers = resolvers or []
        self.add_options(options or [])

    def add_options(self, options: List[Option]) -> Config:
        for option in options:
            self.add_option(option)
        return self

    def add_option(
            self,
            option: Option
    ) -> Config:
        if option.section is UnsetParameter:
            option.section = self.section
        self._options.add(option.bind(self))
        return self

    @property
    def options(self) -> Set[Option]:
        return self._options | set()

    def __add__(self, other: OptionResolver):

        return Config(
            options=[],
            # reverse the readers so that config operations
            # can work like so:
            # big_config = defaults + config1 + config2
            resolvers=[other, self]
        )

    def get_flat(self) -> Tuple[Set, List]:

        resolvers = [r for r in self.resolvers if isinstance(r, DirectResolver)]
        options = self._options

        for resolver in [r for r in self.resolvers if isinstance(r, Config)]:
            new_options, new_resolvers = resolver.get_flat()
            resolvers += new_resolvers
            options |= new_options

        return options, resolvers

    # all children options and readers now belong to this
    def flatten(self):
        options, readers = self.get_flat()
        self._options = options
        self.resolvers = readers

    def get_option(self, option: Union[str, Option], section: str = UnsetParameter) -> Option:
        # find the option in our resolver hierarchy
        # if multiple resolver define an option then the newly added ones have precedence

        if isinstance(option, Option):
            return option

        # look for option in our default section
        if isinstance(option, str):
            name = option
            if section is UnsetParameter:
                section = self.section
        else:
            raise ConfigError('Can not get requested option')

        for option in self._options:
            if option.name == name and option.section == section:
                return option
        else:
            # search deeper for this option
            # only config resolver hold options
            for resolver in filter(lambda x: isinstance(x, Config), self.resolvers):
                try:
                    return resolver.get_option(name, section)
                except UndefinedOptionError:
                    continue
            raise UnassignedOptionError(f'Undefined option {name}')

    def read(self, option: Union[str, Option], section: str = UnsetParameter) -> Any:
        # determine the value of an option only using the local readers
        # do not propagate to other BaseConfigs
        option = self.get_option(option, section)

        if option not in self._options:
            raise ConfigError(f'Reader does not have option {option.name}')

        if not self.resolvers:
            raise NoDirectResolversError

        for reader in [rd for rd in self.resolvers if isinstance(rd, DirectResolver)]:
            try:
                result = reader.read(option)
                if result is not UnsetParameter:
                    return result
            except UnassignedOptionError:
                continue

        raise UnassignedOptionError

    def __getitem__(self, option: Union[str, Tuple[str, str], Option]) -> Any:
        return self.get_option(option).read()

    def cache(self) -> ConfigCache:
        output = defaultdict(dict)
        for option in self.options:
            output[option.section][option.name] = option.read()
        return ConfigCache(dict(output))


class ConfigCache:

    def __init__(self, resolved_options: Dict, section=None):
        self._index = resolved_options
        self.section = section              # Default section to retrieve from

    def __getitem__(self, name):
        return self._index[self.section][name]

    def section(self, section):
        return self._index[section]

    def get(self, name, section=None):
        return self._index[section][name]

    @property
    def dict(self):
        return self._index


class DirectResolver(OptionResolver):
    # this will directly return the value of an option
    # from the config input
    @abstractmethod
    def read(self, option: Option) -> Any:
        pass


class EnvReader(DirectResolver):

    # get config option values from the environment
    def read(self, option: Option):
        try:
            return os.environ[self._env_name(option.name)]
        except KeyError:
            option.attempts.append(
                f'{self} could not find value in environment'
            )
            return UnsetParameter

    def __str__(self):
        return f'{self.__class__.__name__}(prefix: {self._prefix})'

    def __init__(self, prefix=None):
        self._prefix = prefix or ''

    def _env_name(self, name: str) -> str:
        return (self._prefix + name).upper()


class IniReader(DirectResolver):
    # get config option value from an .ini file
    def __init__(self, filepath: str, section: str = None, sections: List[str] = None):
        self._filepath = filepath
        with open(filepath, 'rt') as f:
            self._config = configparser.ConfigParser()
            self._config.read_file(f)

        if sections is not None:
            self._sections = sections
        elif section is not None:
            self._sections = [section]
        else:
            raise ConfigError('Need to configure ONLY one of "section" or "sections"')

    def __str__(self):
        return f'{self.__class__.__name__}({self._filepath})'

    def read(self, option: Option):
        for section in self._sections:
            try:
                return self._config[section][option.name]
            except KeyError:
                option.attempts.append(
                    f'{self} could not find value in section {section}'
                )
        else:
            return UnsetParameter
