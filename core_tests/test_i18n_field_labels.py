import sys
from pathlib import Path
import unittest
import polib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_i18n import _field_labels, _normalize_field_labels, _normalize_source_terms


class FieldLabelCatalogTests(unittest.TestCase):
    def test_renamed_code_term_keeps_runtime_marker(self):
        catalog = polib.POFile()
        catalog.append(polib.POEntry(msgid='Two-channel targets and hourly temperature history',
                                    comment='module: iot_control_center\nodoo-python',
                                    occurrences=[('code:addons/iot_control_center/models/iot_control_board.py', '0')]))
        _normalize_source_terms(catalog)
        self.assertIn('odoo-python', catalog.find('Temperature settings and hourly history').comment)

    def test_old_native_export_reference_cannot_override_new_label(self):
        reference = 'model:ir.model.fields,field_description:iot_control_center.field_iot_instrument__target_a'
        view = ('model_terms:ir.ui.view,arch_db:iot_control_center.another_view', '')
        catalog = polib.POFile()
        catalog.append(polib.POEntry(msgid='Target A', msgstr='old', occurrences=[(reference, ''), view]))
        catalog.append(polib.POEntry(msgid='Requested Temperature', msgstr='new',
                                    occurrences=[('code:addons/iot_control_center', '0')]))
        _normalize_field_labels(catalog, {reference: 'Requested Temperature'})
        self.assertEqual(catalog.find('Target A').occurrences, [view])
        self.assertEqual(catalog.find('Requested Temperature').occurrences, [(reference, '')])
        self.assertEqual(catalog.find('Requested Temperature').msgstr, 'new')

    def test_current_heater_source_labels_are_authoritative(self):
        labels = _field_labels()
        prefix = 'model:ir.model.fields,field_description:iot_control_center.field_iot_instrument__'
        self.assertEqual(labels[prefix + 'target_a'], 'Requested Temperature')
        self.assertEqual(labels[prefix + 'temperature_a'], 'Liquid Temperature')
        self.assertEqual(labels[prefix + 'fault_a'], 'Heater Alarm')
