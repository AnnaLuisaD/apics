from __future__ import unicode_literals
import os
import sys
import transaction
from collections import defaultdict
import csv
import codecs
import re
from cStringIO import StringIO

from path import path

from clld.db.meta import DBSession, Base
from clld.db.models import common
from clld.db.util import compute_language_sources
from clld.util import LGR_ABBRS, slug
from clld.scripts.util import setup_session, Data

from apics import models


def read(table):
    """Read APiCS data from a csv file exported from filemaker.
    """
    data = path('/home/robert/venvs/clld/data/apics-data')
    with codecs.open(data.joinpath('%s.csv' % table), encoding='utf8') as fp:
        content = StringIO(fp.read().replace('\r', '__newline__').encode('utf8'))
        content.seek(0)

    for item in csv.DictReader(content):
        for key in item:
            item[key] = item[key].decode('utf8').replace('__newline__', '\n')
        yield item


def usage(argv):
    cmd = os.path.basename(argv[0])
    print('usage: %s <config_uri>\n'
          '(example: "%s development.ini")' % (cmd, cmd))
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        usage(sys.argv)

    setup_session(sys.argv[1])
    data = Data()

    with transaction.manager:
        for key, value in {
            'publication.sitetitle': 'The Atlas of Pidgin and Creole Language Structures',
            'publication.editors': 'Susanne Maria Michaelis, Philippe Maurer, Martin Haspelmath, and Magnus Huber',
            'publication.year': '2013',
            'publication.publisher': 'MPI EVA',
            'publication.place': 'Leipzig',
        }.items():
            DBSession.add(common.Config(key=unicode(key), value=unicode(value)))

        colors = dict((row['ID'], row['RGB_code']) for row in read('Colours'))

        for id_, name in LGR_ABBRS.items():
            DBSession.add(common.GlossAbbreviation(id=id_, name=name))

        for row in read('References'):
            year = ', '.join(m.group('year') for m in re.finditer('(?P<year>(1|2)[0-9]{3})', row['Year']))
            title = row['Article_title'] or row['Book_title']
            kw = dict(
                id=row['Reference_ID'],
                name=row['Reference_name'],
                description=title,
                authors=row['Authors'],
                year=year,
            )
            p = data.add(common.Source, row['Reference_ID'], **kw)
            DBSession.flush()

            for attr in [
                'Additional_information',
                'Article_title',
                'BibTeX_type',
                'Book_title',
                'City',
                'Editors',
                'Full_reference',
                'Issue',
                'Journal',
                'Language_codes',
                'LaTeX_cite_key',
                'Pages',
                'Publisher',
                'Reference_type',
                'School',
                'Series_title',
                'URL',
                'Volume',
            ]:
                if row.get(attr):
                    DBSession.add(common.Source_data(
                        object_pk=p.pk,
                        key=attr,
                        value=row[attr]))

        for row in read('Features'):
            if not row['Feature_code']:
                continue

            wals_id = row['WALS_No.'].split('.')[0].strip()
            if wals_id and not re.match('[0-9]+', wals_id):
                print('--> problem with wals number:', row['Feature_code'], row['WALS_No.'])
                wals_id = None

#(u'--> problem with wals number:', u'propo', u'-2457.000000') 24 and 57
#(u'--> problem with wals number:', u'genad', u'-30.000000') 30
#(u'--> problem with wals number:', u'posta', u'-69.000000') 69
#(u'--> problem with wals number:', u'loccl', u'-23.000000') 23
#(u'--> problem with wals number:', u'passc', u'-107.000000') 107
#(u'--> problem with wals number:', u'relip', u'-123.000000') 123

            if wals_id:
                wals_id += 'A'
            kw = dict(
                name=row['Feature_name'],
                id=row['Feature_code'],
                description=row['Feature_annotation_publication'],
                feature_type='default',
                wals_id=wals_id,
            )
            p = data.add(models.Feature, row['Feature_code'], **kw)

            names = {}

            for i in range(1, 10):
                id_ = '%s-%s' % (row['Feature_code'], i)
                if row['Value%s' % i].strip() or row['Value%s_publication' % i].strip():
                    name = row['Value%s_publication' % i].strip()
                    if not name:
                        name = row['Value%s' % i].strip()
                    if name in names:
                        name += ' (%s)' % i
                    names[name] = 1
                    kw = dict(id=id_, name=name, parameter=p)
                    de = data.add(common.DomainElement, id_, **kw)
                    DBSession.flush()
                    d = common.DomainElement_data(
                        object_pk=de.pk,
                        key='color',
                        # TODO: fix random color assignment!
                        value=colors.get(row['Value_%s_colour_ID' % i], colors.values()[0]))
                    DBSession.add(d)

        DBSession.flush()

        for row in read('People'):
            #
            # TODO: store alternative email and website in data?
            #
            kw = dict(
                name='%(First name)s %(Last name)s' % row,
                id=slug('%(Last name)s%(First name)s' % row),
                email=row['Contact Email'].split()[0] if row['Contact Email'] else None,
                url=row['Contact Website'].split()[0] if row['Contact Website'] else None,
                address=row['Contact_address'],
            )
            data.add(common.Contributor, row['Author ID'], **kw)

        DBSession.flush()

        for row in read('Languages'):
            lon, lat = [float(c.strip()) for c in row['Coordinates'].split(',')]
            kw = dict(
                name=row['Language_name'],
                id=str(row['Language_number']),
                latitude=lat,
                longitude=lon,
                region=row['Category_region'],
                base_language=row['Category_base_language'],
            )
            data.add(models.Lect, row['Language_ID'], **kw)
            data.add(common.Contribution, row['Language_ID'],
                **dict(id=row['Language_ID'], name=row['Language_name']))

            iso = None
            if len(row['ISO_code']) == 3:
                iso = row['ISO_code'].lower()
                if 'iso:%s' % row['ISO_code'] not in data['Identifier']:
                    data.add(common.Identifier, 'iso:%s' % row['ISO_code'],
                        id=row['ISO_code'].lower(), name=row['ISO_code'].lower(), type='iso639-3')

                DBSession.add(common.LanguageIdentifier(
                    language=data['Lect'][row['Language_ID']],
                    identifier=data['Identifier']['iso:%s' % row['ISO_code']]))

            if row['Language_name_ethnologue']:
                if row['Language_name_ethnologue'] not in data['Identifier']:
                    data.add(common.Identifier, row['Language_name_ethnologue'],
                        id=iso or 'ethnologue:%s' % row['Language_name_ethnologue'],
                        name=row['Language_name_ethnologue'],
                        type='ethnologue')

                DBSession.add(common.LanguageIdentifier(
                    language=data['Lect'][row['Language_ID']],
                    identifier=data['Identifier'][row['Language_name_ethnologue']]))

        DBSession.flush()

        for row in read('Sociolinguistic_features'):
            kw = dict(
                name='%s (S)' % row['Sociolinguistic_feature_name'],
                id=row['Sociolinguistic_feature_code'],
                feature_type='sociolinguistic',
            )
            p = data.add(models.Feature, row['Sociolinguistic_feature_code'], **kw)

            names = {}

            for i in range(1, 7):
                id_ = '%s-%s' % (row['Sociolinguistic_feature_code'], i)
                if row['Value%s' % i].strip():
                    name = row['Value%s' % i].strip()
                    if name in names:
                        name += ' (%s)' % i
                    names[name] = 1
                    kw = dict(id=id_, name=name, parameter=p)
                    de = data.add(common.DomainElement, id_, **kw)

        DBSession.flush()

        for row in read('Language_references'):
            if row['Reference_ID'] not in data['Source']:
                print('missing source for language: %s' % row['Reference_ID'])
                continue
            if row['Language_ID'] not in data['Contribution']:
                print('missing contribution for language reference: %s' % row['Language_ID'])
                continue
            source = data['Source'][row['Reference_ID']]
            DBSession.add(common.ContributionReference(
                contribution=data['Contribution'][row['Language_ID']],
                source=source,
                description=row['Pages'],
                key=source.id))

        lects = defaultdict(lambda: 1)
        lect_map = {}
        records = {}
        false_values = {}
        no_values = {}
        for row in read('Data'):
            lid = row['Language_ID']
            if row['Lect_attribute'].lower() != 'my default lect':
                if (row['Language_ID'], row['Lect_attribute']) in lect_map:
                    lid = lect_map[(row['Language_ID'], row['Lect_attribute'])]
                else:
                    lang = data['Lect'][row['Language_ID']]
                    c = lects[row['Language_ID']]
                    lid = '%s-%s' % (row['Language_ID'], c)
                    kw = dict(
                        name='%s (%s)' % (lang.name, row['Lect_attribute']),
                        id='%s-%s' % (lang.id, c),
                        latitude=lang.latitude,
                        longitude=lang.longitude,
                        description=row['Lect_attribute'],
                        default_lect=False,
                    )
                    data.add(models.Lect, lid, **kw)
                    lects[row['Language_ID']] += 1
                    lect_map[(row['Language_ID'], row['Lect_attribute'])] = lid

            if row['Data_record_id'] in records:
                print('%s already seen' % row['Data_record_id'])
                continue
            else:
                records[row['Data_record_id']] = 1

            valueset = data.add(
                common.ValueSet,
                row['Data_record_id'],
                id=row['Data_record_id'],
                parameter=data['Feature'][row['Feature_code']],
                language=data['Lect'][lid],
                contribution=data['Contribution'][row['Language_ID']],
                description=row['Comments_on_value_assignment'],
            )

            one_value_found = False
            for i in range(1, 10):
                if row['Value%s_true_false' % i].strip() != 'True':
                    if row['Value%s_true_false' % i].strip() == 'False':
                        false_values[row['Data_record_id']] = 1
                    continue

                one_value_found = True
                id_ = '%s-%s' % (row['Data_record_id'], i)
                kw = dict(
                    id=id_,
                    valueset=valueset,
                    domainelement=data['DomainElement']['%s-%s' % (row['Feature_code'], i)],
                    confidence=row['Value%s_confidence' % i],
                    frequency=float(row['c_V%s_frequency_normalised' % i]),
                )
                v = data.add(common.Value, id_, **kw)

                sort_prefix = {
                    'Marginal': 'e_',
                    'Minority': 'd_',
                    'About half': 'c_',
                    'Majority': 'b_',
                    'Pervasive': 'a_',
                }

                frequency = row['Value%s_frequency_text' % i] or 'Pervasive'

                assert frequency in sort_prefix
                DBSession.flush()
                DBSession.add(common.Value_data(
                    object_pk=v.pk,
                    key='relative_importance',
                    value=sort_prefix[frequency] + frequency))

            if not one_value_found:
                no_values[row['Data_record_id']] = 1
                #print('Data without values: %s' % row['Data_record_id'])

        DBSession.flush()

        for row in read('Examples'):
            #
            # TODO: honor row['Lect'] -> (row['Language_ID'], row['Lect']) in lect_map!
            #
            if not row['Language_ID'].strip():
                print('example without language: %s' % row['Example_number'])
                continue
            id_ = '%(Language_ID)s-%(Example_number)s' % row

            atext = row['Analyzed_text'] or row['Text']
            if not row['Gloss'] or not atext:
                print row
                continue

            kw = dict(
                id=id_,
                name=row['Text'],
                description=row['Translation'],
                source=row['Type'],
                comment=row['Comments'],
                gloss='\t'.join(row['Gloss'].split()),
                analyzed='\t'.join(atext.split()),
                original_script=row['Original_script'],
            )
            p = data.add(common.Sentence, id_, **kw)
            p.language = data['Lect'][row['Language_ID']]

            if row['Reference_ID']:
                source = data['Source'][row['Reference_ID']]
                r = common.SentenceReference(
                    sentence=p,
                    source=source,
                    key=source.id,
                    description=row['Reference_pages'],
                )
                DBSession.add(r)

        DBSession.flush()

        records = {}
        #for row in read('Sociolinguistic_data'):
        #    if row['Sociolinguistic_data_record_id'] in records:
        #        print('%s already seen' % row['Sociolinguistic_data_record_id'])
        #        continue
        #    else:
        #        records[row['Sociolinguistic_data_record_id']] = 1
        #
        #    if row['Comments_on_value_assignment']:
        #        DBSession.add(models.ParameterContribution(
        #            comment=row['Comments_on_value_assignment'],
        #            parameter=data['Feature'][row['Sociolinguistic_feature_code']],
        #            contribution=data['Contribution'][row['Language_ID']]))
        #
        #    one_value_found = False
        #    for i in range(1, 7):
        #        if row['Value%s_true_false' % i].strip() != 'True':
        #            continue
        #
        #        if '%s-%s' % (row['Sociolinguistic_feature_code'], i) not in data['DomainElement']:
        #            print('sociolinguistic data point without domainelement: %s' % row['Sociolinguistic_data_record_id'])
        #            continue
        #
        #        one_value_found = True
        #        id_ = 's-%s-%s' % (row['Sociolinguistic_data_record_id'], i)
        #        kw = dict(
        #            id=id_,
        #            language=data['Lect'][row['Language_ID']],
        #            parameter=data['Feature'][row['Sociolinguistic_feature_code']],
        #            contribution=data['Contribution'][row['Language_ID']],
        #            domainelement=data['DomainElement']['%s-%s' % (row['Sociolinguistic_feature_code'], i)],
        #            confidence=row['Value%s_confidence' % i],
        #        )
        #        data.add(common.Value, id_, **kw)
        #    if not one_value_found:
        #        print('Sociolinguistic data without values: %s' % row['Sociolinguistic_data_record_id'])

        DBSession.flush()

        for prefix, num_values in [
            ('D', 10),
            #('Sociolinguistic_d', 7),
        ]:
            for row in read(prefix + 'ata_references'):
                if row['Reference_ID'] not in data['Source']:
                    print('Reference with unknown source: %s' % row['Reference_ID'])
                    continue
                source = data['Source'][row['Reference_ID']]
                try:
                    DBSession.add(common.ValueSetReference(
                        valueset=data['ValueSet'][row[prefix + 'ata_record_id']],
                        source=source,
                        key=source.id,
                        description=row['Pages'],
                    ))
                except KeyError:
                    print('Reference for unknown dataset: %s' % row[prefix + 'ata_record_id'])
                    continue

                #one_value_found = False
                #for i in range(1, num_values):
                #    value = '%s-%s' % (row[prefix + 'ata_record_id'], i)
                #    if value not in data['Value']:
                #        continue
                #
                #    one_value_found = True
                #    if row['Reference_ID'] not in data['Source']:
                #        print('Reference with unknown source: %s' % row['Reference_ID'])
                #        continue
                #    source = data['Source'][row['Reference_ID']]
                #    r = common.ValueReference(
                #        value=data['Value'][value],
                #        source=source,
                #        key=source.id,
                #        description=row['Pages'],
                #    )
                #    DBSession.add(r)
                #if not one_value_found:
                #    if row[prefix + 'ata_record_id'] in false_values:
                #        print('--> reference for false value!')
                #    elif row[prefix + 'ata_record_id'] in no_values:
                #        print('--> reference for dataset with no values!')
                #    #
                #    # TODO: put into ValueSetReference!
                #    #
                #    #print('Reference with unknown value: %s' % row[prefix + 'ata_record_id'])

        DBSession.flush()

        missing = 0
        for row in read('Value_examples'):
            try:
                DBSession.add(common.ValueSentence(
                    value=data['Value']['%(Data_record_id)s-%(Value_number)s' % row],
                    sentence=data['Sentence']['%(Language_ID)s-%(Example_number)s' % row],
                    description=row['Notes'],
                ))
            except KeyError:
                missing += 1
        print('%s Value_examples are missing data' % missing)

        print('%s data sets with false values' % len(false_values))
        print('%s data sets without values' % len(no_values))

        for i, row in enumerate(read('Contributors')):
            kw = dict(
                contribution=data['Contribution'][row['Language ID']],
                contributor=data['Contributor'][row['Author ID']]
            )
            if row['Order_of_appearance']:
                kw['ord'] = int(float(row['Order_of_appearance']))
            data.add(common.ContributionContributor, i, **kw)

        DBSession.flush()


def prime_cache():
    setup_session(sys.argv[1])

    with transaction.manager:
        compute_language_sources()


if __name__ == '__main__':
    if len(sys.argv) == 2:
        main()
    prime_cache()
