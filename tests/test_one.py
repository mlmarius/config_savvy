import os

import pytest

from config_savvy import Config, EnvReader, IniReader, Option, ConfigError, UndefinedOptionError


def test_one(caplog):
    os.environ['OPTION2'] = '33'
    os.environ['OPTION3'] = 'spam'

    config1 = Config(
        options=[
            # Option with a default value. Found nowhere else
            Option('option1', 1),

            # Option with a specified value, overriden in environment.
            # Should return specified balue
            Option('option2', value=2, processor=int),

            # this one has a default value and an environment value
            # it should return the environment value
            Option('option3', 3)
        ],
        resolvers=[
            # WARNING: When searching in environment, option names
            # are uppercased
            EnvReader()
        ]
    )

    assert config1['option1'] == 1, 'You only had 1 job: return the default value of the option'
    assert config1['option2'] == 2, 'This item had a hardcoded value. Where is it?'
    assert config1['option3'] == 'spam', 'We should have received the environment value'

    config2 = Config(
        options=[
            # we are overwriting a config option from the previous config
            Option('option3', value='cat'),
            Option('option4', 4)
        ],
        resolvers=[
            IniReader('tests/config.ini', sections=['bitbucket.org', 'topsecret.server.com'])
        ]
    )

    # we are merging 2 configs
    # if an option is defined in both
    # the config2 will overwrite config1's option
    config3 = config1 + config2

    assert config2['option3'] == 'cat', 'This option should have been overridden after the merge'
    assert config3['option4'] == 4

    # should raise value error because we tried to access an option
    # that is not defined in the config
    with pytest.raises(UndefinedOptionError):
        assert config3['User'] == 'hg'


    config4 = config1 + Config(
        [IniReader('tests/config.ini', sections=['bitbucket.org', 'topsecret.server.com'])],
        options=[
            Option('ForwardX11'),
            Option('Port'),
            Option('Undefined')
        ]
    )

    # Carefull! Even if you define searching in multiple sections,
    # once a value is not found in the first section, then it will
    # be searched in the DEFAULT section
    assert config4['ForwardX11'] == 'yes'

    # This item is found in our second searched list.
    # It will only be returned if the first section does not have it
    # AND if it is not defined in the DEFAULT section
    assert config4['Port'] == '50022'

    # We raise ValueError if the option is defined
    # but we can't find its value
    with pytest.raises(ConfigError):
        assert config4['Undefined']


def test_add_option():
    c = Config()
    c.add_option(Option('option1', 1))
    assert c.section is None
    assert c['option1'] is 1
    c.section = 'SECTION1'
    c.add_option(Option('option2', 2))
    opt = c.get_option('option2', 'SECTION1')
    assert opt.section == 'SECTION1'
    assert opt.read() == 2


def test_addition():
    os.environ['OPTION2'] = '33'
    os.environ['OPTION3'] = 'spam'
    os.environ['USER'] = 'EnvironUser'

    config1 = Config(
        options=[
            Option('option1', 1),
            Option('ForwardX11'),
            Option('Port'),
        ],
        resolvers=[
            EnvReader(),
        ]
    )

    with pytest.raises(ConfigError):
        assert config1['User'] == 'EnvironUser'

    config2 = Config(
        options=[
            Option('User'),
        ],
        resolvers=[
            IniReader('tests/config.ini', sections=['bitbucket.org', 'topsecret.server.com'])
        ]
    )

    config1 = Config(
        options=[
            Option('option1', 1),
            Option('ForwardX11'),
            Option('Port'),
            Option('User')
        ],
        resolvers=[
            EnvReader(),
        ]
    )

    config = config1 + config2
    assert config['User'] == "hg"

    config = config2 + config1
    assert config['User'] == "EnvironUser"


def test_cache():

    os.environ.clear()

    os.environ['OPTION2'] = '33'
    os.environ['OPTION3'] = 'spam'

    config = Config(
        options=[
            Option('option1', 1),
            Option('User'),
            Option('ForwardX11'),
            Option('Port'),
        ],
        resolvers=[
            EnvReader(),
            IniReader('tests/config.ini', sections=['bitbucket.org', 'topsecret.server.com'])
        ]
    )

    config.section = "OTHER"
    config.add_option(Option('option4', 'yes'))

    cache = config.cache()
    assert cache['option1'] == 1
    assert cache['User'] == 'hg'

    # warning. section bitbucket.org does not have this option so it goes to DEFAULT
    # if the DEFAULT section is defined
    assert cache['ForwardX11'] == 'yes'
    assert cache['Port'] == '50022'
    assert cache.get('option4', 'OTHER') == 'yes'

    expected = {
        None: {
            'ForwardX11': 'yes',
            'Port': '50022',
            'User': 'hg',
            'option1': 1
        },
        'OTHER': {'option4': 'yes'}
    }
    assert cache.dict == expected


def test_none_works():
    config = Config(
        options=[
            Option('option1', None),
        ]
    )
    assert config['option1'] is None

def test_get_option():

    config1 = Config(name="config1", options=[
        Option('option1', 1)
    ])

    # get it by name
    opt = config1.get_option('option1')
    assert opt.read() is 1

    # get it by instance
    opt2 = config1.get_option(opt)
    assert opt2.read() is 1

    config2 = Config(name="config2", options=[
        Option('option1', 2)
    ])

    # option1 is now shadowed by config2's option1
    config3 = config1 + config2

    # but when we search for an option by instance
    # we get the exact instance
    opt3 = config3.get_option(opt)
    assert opt3.read() is 1

    # when we query by option name
    # we get the "topmost" option
    assert config3['option1'] is 2


def test_add_remove_options():

    config = Config()
    opt1 = Option('option1', 1)
    config.set_option(opt1)
    assert config['option1'] == 1
    config.remove_option('option1')
    with pytest.raises(UndefinedOptionError):
        assert config['option1'] == 1

    config1 = Config(name="config1")
    option11 = Option('option11', 11)
    option12 = Option('option12', 12)
    config1.add_options([
        option11, option12
    ])

    config2 = Config(name="config2")
    option21 = Option('option21', 21)
    option22 = Option('option22', 22)
    config2.add_options([
        option21, option22,
        Option('option11', 'test')  # config2 shadows one of config1's options
    ])

    config3 = config1 + config2
    assert config3['option11'] == 'test', "Option was not shadowed"

    # once we remove the shadowing
    # option we get the base option again
    config3.remove_option('option11')
    assert config3['option11'] == 11

    config1.set_option(Option('option11', 'another value'))

    assert config1['option11'] == 'another value'

    # config3 also has the updated value
    assert config3['option11'] == 'another value'


def test_ini_reader():
    reader = IniReader('tests/config.ini', sections=['bitbucket.org', 'topsecret.server.com'])
    assert reader._config.sections() == ['bitbucket.org', 'topsecret.server.com']

