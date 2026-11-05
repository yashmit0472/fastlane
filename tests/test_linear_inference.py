import io
import pickle
import unittest
import numpy as np
import pandas as pd
from ml.inference.linear import LinearModel,ParameterReader,load_linear


class LinearInferenceTests(unittest.TestCase):
    def test_imputation_indicators_scaling_and_unknown_category(self):
        blocks=[{'kind':'numeric','name':'numeric','columns':['a','b'],'statistics':[10,4],'indicators':[1],'mean':[2,2,.5],'scale':[2,2,.5]},
                {'kind':'categorical','name':'categorical','columns':['driver'],'categories':[['known','other']]}]
        model=LinearModel(blocks,[1,2,3,4,5],.2)
        frame=pd.DataFrame({'a':[4,6],'b':[np.nan,2],'driver':['known','new']})
        transformed=model.named_steps['features'].transform(frame)
        np.testing.assert_allclose(transformed,[[1,1,1,1,0],[2,0,-1,0,0]])
        np.testing.assert_allclose(model.decision_function(frame),[10.2,-.8])
        probabilities=model.predict_proba(frame); np.testing.assert_allclose(probabilities.sum(axis=1),1)
        np.testing.assert_allclose(probabilities[:,1],1/(1+np.exp(-np.array([10.2,-.8]))))
        self.assertEqual(len(model.named_steps['features'].get_feature_names_out()),5)

    def test_reader_rejects_executable_globals(self):
        with self.assertRaisesRegex(ValueError,'Unsupported model parameter'):
            ParameterReader(io.BytesIO(pickle.dumps(eval))).load()

    def test_bad_dimensions_and_external_paths_fail_closed(self):
        with self.assertRaises(ValueError): LinearModel([], [1],0)
        with self.assertRaisesRegex(ValueError,'local model artifact'): load_linear('C:/untrusted.pkl')


if __name__=='__main__': unittest.main()
