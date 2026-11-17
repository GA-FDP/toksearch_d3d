"""Run the named test modules in order, in one process."""
import os, sys, unittest
sys.path.insert(0, os.getcwd())
os.environ.setdefault("TOKSEARCH_INTEGRATION", "yes")
os.environ.setdefault("TOKSEARCH_PTDATA_TEST", "yes")
suite = unittest.TestSuite()
for name in sys.argv[1:]:
    suite.addTests(unittest.TestLoader().loadTestsFromName(name))
res = unittest.TextTestRunner(verbosity=2).run(suite)
sys.stdout.flush(); sys.stderr.flush()
os._exit(0 if res.wasSuccessful() else 1)
