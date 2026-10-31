import unittest

from cogs.errores import AntiSpam, censurar_secretos


class CensurarSecretosTests(unittest.TestCase):
    def test_censura_token_groq_y_clabe(self):
        env = {
            'DISCORD_TOKEN': 'token-super-secreto',
            'GROQ_API_KEY': 'gsk_clave_secreta',
            'CLABE': '012345678901234567',
        }
        texto = (
            'token=token-super-secreto key=gsk_clave_secreta '
            'clabe=012345678901234567'
        )
        salida = censurar_secretos(texto, env)
        self.assertNotIn(env['DISCORD_TOKEN'], salida)
        self.assertNotIn(env['GROQ_API_KEY'], salida)
        self.assertNotIn(env['CLABE'], salida)
        self.assertEqual(salida.count('[censurado]'), 3)

    def test_no_censura_valores_demasiado_cortos(self):
        self.assertEqual(
            censurar_secretos('precio 60', {'CLABE': '60'}),
            'precio 60',
        )

    def test_texto_vacio(self):
        self.assertEqual(censurar_secretos(None, {}), '')


class AntiSpamTests(unittest.TestCase):
    def setUp(self):
        self.spam = AntiSpam(ventana=600)

    def test_primer_error_notifica_y_siguientes_se_acumulan(self):
        self.assertEqual(self.spam.registrar('error-1', ahora=0), ('primero', 1))
        self.assertIsNone(self.spam.registrar('error-1', ahora=10))
        self.assertIsNone(self.spam.registrar('error-1', ahora=20))

    def test_flush_envia_resumen_al_cerrar_ventana(self):
        self.spam.registrar('error-1', ahora=0)
        self.spam.registrar('error-1', ahora=10)
        self.spam.registrar('error-1', ahora=20)
        self.assertEqual(self.spam.flush(ahora=599), [])
        self.assertEqual(self.spam.flush(ahora=600), [('error-1', 3)])
        self.assertEqual(self.spam.flush(ahora=601), [])

    def test_error_tras_ventana_incluye_conteo_anterior(self):
        self.spam.registrar('error-1', ahora=0)
        self.spam.registrar('error-1', ahora=10)
        self.assertEqual(self.spam.registrar('error-1', ahora=600), ('resumen', 2))
        self.assertIsNone(self.spam.registrar('error-1', ahora=601))

    def test_errores_distintos_no_se_mezclan(self):
        self.assertEqual(self.spam.registrar('error-1', ahora=0), ('primero', 1))
        self.assertEqual(self.spam.registrar('error-2', ahora=1), ('primero', 1))
        self.assertIsNone(self.spam.registrar('error-1', ahora=2))
        self.assertIsNone(self.spam.registrar('error-2', ahora=3))


if __name__ == '__main__':
    unittest.main()
