from __future__ import annotations

import configparser
import logging
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import List, Callable, Dict, Union, Tuple, Any, Set

LOGGER = logging.getLogger('config_savvy')


class BaseOption(ABC):
    def __hash__(self):
        return hash((self.name, self.section))

    def __eq__(self, other: Option):
        return self.section == other.section and self.name == other.name

    def __str__(self):
        return self.name


class Option(BaseOption):

    def __init__(
            self,
            name: str,
            default=None,
            value=None,
            processor: Callable = None,
            section: str = None,
            description: str = None
    ):
        self.name = name
        self._processor = processor or (lambda x: x)
        self._default = default
        self.section = section
        self._value = value
        self.description = description

    @property
    def value(self):
        if self._value:
            return self._processor(self._value)

    @property
    def default(self):
        if self._default:
            return self._processor(self._default)


class BoundOption(BaseOption):
    def __init__(self,
                 config_option: Option,
                 reader: BaseConfig
                 ):
        self._option = config_option
        self._reader = reader

    def __getattr__(self, name):
        return self._option.__getattribute__(name)

    def resolve(self):
        return self._reader.resolve(self)


class BaseConfig(ABC):

    def __init__(self, options: List[Option] = None, readers: List[BaseConfig] = None):
        self.readers = readers or []
        self._options = set(options or [])

    def get_flat(self) -> Union[Set, List]:
        if isinstance(self, BaseConfigReader):
            return set(), [self]

        readers = []
        options = self._options

        for reader in self.readers:
            new_options, new_readers = reader.get_flat()
            readers += new_readers
            options |= new_options

        return options, readers

    def flatten(self):
        readers, options = self.get_flat()
        self.readers = readers
        self._options = options

    @abstractmethod
    def get_option(self, name: str, section: str = None) -> BoundOption:
        pass

    @abstractmethod
    def resolve(self, option: Option) -> Any:
        pass

    @abstractmethod
    def options(self) -> Set[Option]:
        pass

    @abstractmethod
    def resolve(self, option: BaseOption):
        pass


class Config(BaseConfig):
    def __init__(self, options: List[Option] = None, readers: List[BaseConfig] = None, section: str = None):
        super().__init__(options, readers)
        # will automatically set the following section to all newly appended ConfigOptions
        self.section = section

    def add_option(
            self,
            name: str,
            default=None,
            value=None,
            processor: Callable = None,
            section: str = None,
            description: str = None
    ) -> Config:

        if section is not None:
            self.section = section

        self._options.add(Option(
            name=name,
            default=default,
            value=value,
            processor=processor,
            description=description,
            section=self.section
        ))
        return self

    def add_reader(self, reader: BaseConfig):
        self.readers.append(reader)

    @property
    def options(self) -> Set[Option]:
        return self._options | set()

    def __add__(self, other: BaseConfig):
        return Config(
            options=[],
            readers=[self, other]
        )

    # all children options and readers now belong to this
    def flatten(self):
        options, readers = self.get_flat()
        self._options = options
        self.readers = readers

    def get_option(self, name: str, section: str = None) -> BoundOption:
        for option in self._options:
            if option.name == name and option.section == section:
                return BoundOption(option, self)
        else:
            # reverse the readers so that config operations
            # can work like so:
            # big_config = defaults + config1 + config2
            for reader in reversed(self.readers):
                try:
                    return reader.get_option(name, section)
                except UndefinedOptionError:
                    continue
            raise UnassignedOptionError(f'Undefined option {name}')

    # determine the value of an option only using the local readers
    # do not propagate to other BaseConfigs
    def resolve(self, option: Option):
        if option not in self._options:
            raise ConfigError(f'Reader does not have option {option.name}')

        attempts = []
        for reader in [rd for rd in self.readers if isinstance(rd, BaseConfigReader)]:
            try:
                return reader.resolve(option)
            except UnassignedOptionError as e:
                attempts += e.attempts

        if option.default is not None:
            return option.default

        raise UnassignedOptionError(f"{option.name} - could not be resolved", attempts)

    def __getitem__(self, item: Union[str, Tuple[str, str], Option]) -> Any:

        if not isinstance(item, Option):
            # look for option in our default section
            if isinstance(item, str):
                item = self.get_option(item, self.section)
            # search option in specific section
            elif isinstance(item, tuple):
                name, section = item
                item = self.get_option(name, section)

        if item.value is not None:
            return item.value

        try:
            return item.resolve()
        except ConfigError as e:
            LOGGER.error(e)
            if item.default is not None:
                return item.default
            for message in e.attempts:
                LOGGER.warning(message)
            raise e

    def cache(self) -> Dict[str, Union[str, bool, int, float]]:
        output = defaultdict(dict)
        for option in self.options:
            output[option.section][option.name] = self[option]
        return dict(output)


class ConfigError(Exception):
    def __init__(self, message=None, attempts=None):
        self.message = message
        self.attempts = attempts


class UndefinedOptionError(ConfigError):
    pass


class UnassignedOptionError(ConfigError):
    pass


class BaseConfigReader(BaseConfig):

    def get_option(self, name: str, section: str = None) -> BoundOption:
        raise UndefinedOptionError()

    @abstractmethod
    def resolve(self, option: Option) -> Any:
        pass

    @property
    def options(self) -> Set[Option]:
        return set()


class EnvConfigReader(BaseConfigReader):

    def resolve(self, option: BaseOption):
        try:
            return os.environ[self._env_name(option.name)]
        except KeyError:
            raise UnassignedOptionError(
                attempts=[
                    f'{self.__class__.__name__} | searching for {option.name} | could not find {self._env_name(option.name)}'
            ])

    def __init__(self, prefix=None):
        super().__init__()
        self._prefix = prefix or ''

    def _env_name(self, name: str) -> str:
        return (self._prefix + name).upper()


class IniConfigReader(BaseConfigReader):
    def __init__(self, filepath: str, section: str = None, sections: List[str] = None):
        super().__init__()
        with open(filepath, 'rt') as f:
            self._config = configparser.ConfigParser()
            self._config.read_file(f)

        if sections is not None:
            self._sections = sections
        elif section is not None:
            self._sections = [section]
        else:
            raise ConfigError('Need to configure ONLY one of "section" or "sections"')

    def resolve(self, option: Option):
        attempts = []
        for section in self._sections:
            try:
                return self._config[section][option.name]
            except KeyError:
                attempts.append(
                    f'{self.__class__.__name__} | searching for {option.name} | not found in section {section}'
                )
        else:
            raise UnassignedOptionError(attempts=attempts)
