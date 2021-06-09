
class DummySession:
	"""A framework-"specific" dummy session that doesn't do anything"""
	async def __aenter__(self):
		return self

	async def __aexit__(self, *tb):
		pass

