import unittest

from cogs.servidor import GestorAlertas


class AlertasTests(unittest.TestCase):
    def setUp(self):
        self.gestor = GestorAlertas()

    def evaluar(self, bateria=None, cargando=False, temperatura=None):
        return self.gestor.evaluar(
            bateria, cargando, temperatura,
            bateria_min=20, bateria_rearme=25,
            temp_max=45, temp_rearme=42,
        )

    def test_bateria_baja_avisa_en_la_primera_revision(self):
        self.assertEqual(
            self.evaluar(bateria=15),
            [{'tipo': 'bateria', 'estado': 'alerta', 'valor': 15}],
        )

    def test_bateria_no_repite_alerta_mientras_sigue_baja(self):
        self.evaluar(bateria=15)
        self.assertEqual(self.evaluar(bateria=18), [])
        self.assertEqual(self.evaluar(bateria=22), [])

    def test_bateria_se_rearma_al_llegar_a_25(self):
        self.evaluar(bateria=15)
        self.assertEqual(
            self.evaluar(bateria=25),
            [{'tipo': 'bateria', 'estado': 'recuperado', 'valor': 25}],
        )
        self.assertEqual(
            self.evaluar(bateria=15),
            [{'tipo': 'bateria', 'estado': 'alerta', 'valor': 15}],
        )

    def test_bateria_recupera_al_empezar_a_cargar(self):
        self.evaluar(bateria=15)
        self.assertEqual(
            self.evaluar(bateria=16, cargando=True),
            [{'tipo': 'bateria', 'estado': 'recuperado', 'valor': 16}],
        )

    def test_bateria_no_alerta_si_ya_esta_cargando(self):
        self.assertEqual(self.evaluar(bateria=15, cargando=True), [])

    def test_temperatura_alta_avisa_y_no_repite(self):
        self.assertEqual(
            self.evaluar(temperatura=46),
            [{'tipo': 'temperatura', 'estado': 'alerta', 'valor': 46}],
        )
        self.assertEqual(self.evaluar(temperatura=44), [])
        self.assertEqual(self.evaluar(temperatura=43), [])

    def test_temperatura_se_rearma_al_bajar_de_42(self):
        self.evaluar(temperatura=46)
        self.assertEqual(
            self.evaluar(temperatura=41),
            [{'tipo': 'temperatura', 'estado': 'recuperado', 'valor': 41}],
        )
        self.assertEqual(
            self.evaluar(temperatura=46),
            [{'tipo': 'temperatura', 'estado': 'alerta', 'valor': 46}],
        )

    def test_bateria_y_temperatura_pueden_avisar_juntas(self):
        avisos = self.evaluar(bateria=10, temperatura=50)
        self.assertEqual(
            [aviso['tipo'] for aviso in avisos],
            ['bateria', 'temperatura'],
        )


if __name__ == '__main__':
    unittest.main()
