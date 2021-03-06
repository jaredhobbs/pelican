import os
import re
import sys
import time
import logging
import argparse

from pelican import signals

from pelican.generators import (ArticlesGenerator, PagesGenerator,
                                StaticGenerator, PdfGenerator,
                                LessCSSGenerator, SourceFileGenerator,
                                TemplatePagesGenerator)
from pelican.log import init
from pelican.settings import read_settings
from pelican.utils import (clean_output_dir, files_changed, file_changed,
                           NoFilesError)
from pelican.writers import Writer

__major__ = 3
__minor__ = 0
__version__ = "{0}.{1}".format(__major__, __minor__)


logger = logging.getLogger(__name__)


class Pelican(object):
    def __init__(self, settings):
        """
        Pelican initialisation, performs some checks on the environment before
        doing anything else.
        """

        # define the default settings
        self.settings = settings
        self._handle_deprecation()

        self.path = settings['PATH']
        self.theme = settings['THEME']
        self.output_path = settings['OUTPUT_PATH']
        self.markup = settings['MARKUP']
        self.delete_outputdir = settings['DELETE_OUTPUT_DIRECTORY']

        self.init_path()
        self.init_plugins()
        signals.initialized.send(self)

    def init_path(self):
        if not any(p in sys.path for p in ['', '.']):
            logger.debug("Adding current directory to system path")
            sys.path.insert(0, '')

    def init_plugins(self):
        self.plugins = self.settings['PLUGINS']
        for plugin in self.plugins:
            # if it's a string, then import it
            if isinstance(plugin, basestring):
                logger.debug("Loading plugin `{0}' ...".format(plugin))
                plugin = __import__(plugin, globals(), locals(), 'module')

            logger.debug("Registering plugin `{0}'".format(plugin.__name__))
            plugin.register()

    def _handle_deprecation(self):

        if self.settings.get('CLEAN_URLS', False):
            logger.warning('Found deprecated `CLEAN_URLS` in settings.'
                        ' Modifying the following settings for the'
                        ' same behaviour.')

            self.settings['ARTICLE_URL'] = '{slug}/'
            self.settings['ARTICLE_LANG_URL'] = '{slug}-{lang}/'
            self.settings['PAGE_URL'] = 'pages/{slug}/'
            self.settings['PAGE_LANG_URL'] = 'pages/{slug}-{lang}/'

            for setting in ('ARTICLE_URL', 'ARTICLE_LANG_URL', 'PAGE_URL',
                            'PAGE_LANG_URL'):
                logger.warning("%s = '%s'" % (setting, self.settings[setting]))

        if self.settings.get('ARTICLE_PERMALINK_STRUCTURE', False):
            logger.warning('Found deprecated `ARTICLE_PERMALINK_STRUCTURE` in'
                        ' settings.  Modifying the following settings for'
                        ' the same behaviour.')

            structure = self.settings['ARTICLE_PERMALINK_STRUCTURE']

            # Convert %(variable) into {variable}.
            structure = re.sub('%\((\w+)\)s', '{\g<1>}', structure)

            # Convert %x into {date:%x} for strftime
            structure = re.sub('(%[A-z])', '{date:\g<1>}', structure)

            # Strip a / prefix
            structure = re.sub('^/', '', structure)

            for setting in ('ARTICLE_URL', 'ARTICLE_LANG_URL', 'PAGE_URL',
                            'PAGE_LANG_URL', 'ARTICLE_SAVE_AS',
                            'ARTICLE_LANG_SAVE_AS', 'PAGE_SAVE_AS',
                            'PAGE_LANG_SAVE_AS'):
                self.settings[setting] = os.path.join(structure,
                                                      self.settings[setting])
                logger.warning("%s = '%s'" % (setting, self.settings[setting]))

        if self.settings.get('FEED', False):
            logger.warning('Found deprecated `FEED` in settings. Modify FEED'
            ' to FEED_ATOM in your settings and theme for the same behavior.'
            ' Temporarily setting FEED_ATOM for backwards compatibility.')
            self.settings['FEED_ATOM'] = self.settings['FEED']

        if self.settings.get('TAG_FEED', False):
            logger.warning('Found deprecated `TAG_FEED` in settings. Modify '
            ' TAG_FEED to TAG_FEED_ATOM in your settings and theme for the '
            'same behavior. Temporarily setting TAG_FEED_ATOM for backwards '
            'compatibility.')
            self.settings['TAG_FEED_ATOM'] = self.settings['TAG_FEED']

        if self.settings.get('CATEGORY_FEED', False):
            logger.warning('Found deprecated `CATEGORY_FEED` in settings. '
            'Modify CATEGORY_FEED to CATEGORY_FEED_ATOM in your settings and '
            'theme for the same behavior. Temporarily setting '
            'CATEGORY_FEED_ATOM for backwards compatibility.')
            self.settings['CATEGORY_FEED_ATOM'] =\
                    self.settings['CATEGORY_FEED']

        if self.settings.get('TRANSLATION_FEED', False):
            logger.warning('Found deprecated `TRANSLATION_FEED` in settings. '
            'Modify TRANSLATION_FEED to TRANSLATION_FEED_ATOM in your '
            'settings and theme for the same behavior. Temporarily setting '
            'TRANSLATION_FEED_ATOM for backwards compatibility.')
            self.settings['TRANSLATION_FEED_ATOM'] =\
                    self.settings['TRANSLATION_FEED']

    def run(self):
        """Run the generators and return"""

        context = self.settings.copy()
        generators = [
            cls(
                context,
                self.settings,
                self.path,
                self.theme,
                self.output_path,
                self.markup,
                self.delete_outputdir
            ) for cls in self.get_generator_classes()
        ]

        for p in generators:
            if hasattr(p, 'generate_context'):
                p.generate_context()

        # erase the directory if it is not the source and if that's
        # explicitely asked
        if (self.delete_outputdir and not
                os.path.realpath(self.path).startswith(self.output_path)):
            clean_output_dir(self.output_path)

        writer = self.get_writer()

        # pass the assets environment to the generators
        if self.settings['WEBASSETS']:
            generators[1].env.assets_environment = generators[0].assets_env
            generators[2].env.assets_environment = generators[0].assets_env

        for p in generators:
            if hasattr(p, 'generate_output'):
                p.generate_output(writer)

        signals.finalized.send(self)

    def get_generator_classes(self):
        generators = [StaticGenerator, ArticlesGenerator, PagesGenerator]

        if self.settings['TEMPLATE_PAGES']:
            generators.append(TemplatePagesGenerator)
        if self.settings['PDF_GENERATOR']:
            generators.append(PdfGenerator)
        if self.settings['LESS_GENERATOR']:  # can be True or PATH to lessc
            generators.append(LessCSSGenerator)
        if self.settings['OUTPUT_SOURCES']:
            generators.append(SourceFileGenerator)

        for pair in signals.get_generators.send(self):
            (funct, value) = pair

            if not isinstance(value, (tuple, list)):
                value = (value, )

            for v in value:
                if isinstance(v, type):
                    logger.debug('Found generator: {0}'.format(v))
                    generators.append(v)

        return generators

    def get_writer(self):
        return Writer(self.output_path, settings=self.settings)


def parse_arguments():
    parser = argparse.ArgumentParser(description="""A tool to generate a
    static blog, with restructured text input files.""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument(dest='path', nargs='?',
        help='Path where to find the content files.',
        default=None)

    parser.add_argument('-t', '--theme-path', dest='theme',
        help='Path where to find the theme templates. If not specified, it'
             'will use the default one included with pelican.')

    parser.add_argument('-o', '--output', dest='output',
        help='Where to output the generated files. If not specified, a '
             'directory will be created, named "output" in the current path.')

    parser.add_argument('-m', '--markup', dest='markup',
        help='The list of markup language to use (rst or md). Please indicate '
             'them separated by commas.')

    parser.add_argument('-s', '--settings', dest='settings',
        help='The settings of the application.')

    parser.add_argument('-d', '--delete-output-directory',
        dest='delete_outputdir',
        action='store_true', help='Delete the output directory.')

    parser.add_argument('-v', '--verbose', action='store_const',
        const=logging.INFO, dest='verbosity',
        help='Show all messages.')

    parser.add_argument('-q', '--quiet', action='store_const',
        const=logging.CRITICAL, dest='verbosity',
        help='Show only critical errors.')

    parser.add_argument('-D', '--debug', action='store_const',
        const=logging.DEBUG, dest='verbosity',
        help='Show all message, including debug messages.')

    parser.add_argument('--version', action='version', version=__version__,
        help='Print the pelican version and exit.')

    parser.add_argument('-r', '--autoreload', dest='autoreload',
        action='store_true',
        help="Relaunch pelican each time a modification occurs"
                             " on the content files.")
    return parser.parse_args()


def get_config(args):
    config = {}
    if args.path:
        config['PATH'] = os.path.abspath(os.path.expanduser(args.path))
    if args.output:
        config['OUTPUT_PATH'] = \
                os.path.abspath(os.path.expanduser(args.output))
    if args.markup:
        config['MARKUP'] = [a.strip().lower() for a in args.markup.split(',')]
    if args.theme:
        abstheme = os.path.abspath(os.path.expanduser(args.theme))
        config['THEME'] = abstheme if os.path.exists(abstheme) else args.theme
    if args.delete_outputdir is not None:
        config['DELETE_OUTPUT_DIRECTORY'] = args.delete_outputdir
    return config


def get_instance(args):

    settings = read_settings(args.settings, override=get_config(args))

    cls = settings.get('PELICAN_CLASS')
    if isinstance(cls, basestring):
        module, cls_name = cls.rsplit('.', 1)
        module = __import__(module)
        cls = getattr(module, cls_name)

    return cls(settings)


def main():
    args = parse_arguments()
    init(args.verbosity)
    pelican = get_instance(args)

    try:
        if args.autoreload:
            files_found_error = True
            while True:
                try:
                    # Check source dir for changed files ending with the given
                    # extension in the settings. In the theme dir is no such
                    # restriction; all files are recursively checked if they
                    # have changed, no matter what extension the filenames
                    # have.
                    if files_changed(pelican.path, pelican.markup) or \
                            files_changed(pelican.theme, ['']):
                        if not files_found_error:
                            files_found_error = True
                        pelican.run()

                    # reload also if settings.py changed
                    if file_changed(args.settings):
                        logger.info('%s changed, re-generating' %
                                    args.settings)
                        pelican = get_instance(args)
                        pelican.run()

                    time.sleep(.5)  # sleep to avoid cpu load
                except KeyboardInterrupt:
                    logger.warning("Keyboard interrupt, quitting.")
                    break
                except NoFilesError:
                    if files_found_error:
                        logger.warning("No valid files found in content. "
                                       "Nothing to generate.")
                        files_found_error = False
                    time.sleep(1)  # sleep to avoid cpu load
                except Exception, e:
                    logger.warning(
                        "Caught exception \"%s\". Reloading." % e.__str__()
                    )
                    continue
        else:
            pelican.run()
    except Exception, e:
        logger.critical(unicode(e))

        if (args.verbosity == logging.DEBUG):
            raise
        else:
            sys.exit(getattr(e, 'exitcode', 1))
