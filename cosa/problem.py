# Copyright 2018 Cristian Mattarei
#
# Licensed under the modified BSD (3-clause BSD) License.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import namedtuple
import configparser
import copy
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Set


from cosa.encoders.formulae import StringParser
from cosa.representation import HTS
from cosa.utils.generic import auto_convert
from cosa.utils.logger import Logger


DEFAULT = "DEFAULT"
GENERAL = "GENERAL"
VERIFICATION = "verification"
LIVENESS = "liveness"
EVENTUALLY = "eventually"
SAFETY = "safety"
PARAMETRIC = "parametric"
LTL = "ltl"
EQUIVALENCE = "equivalence"
SIMULATION = "simulation"
DETERMINISTIC = "deterministic"
FORMULA = "formula"
MODEL_FILE = "model_file"

class VerificationStatus(object):
    UNC = "UNCHECKED"
    UNK = "UNKNOWN"
    TRUE = "TRUE"
    FALSE = "FALSE"

    @staticmethod
    def convert(status):
        if type(status) == bool:
            return VerificationStatus.TRUE if status else VerificationStatus.FALSE

        if status.upper() in [VerificationStatus.TRUE,\
                              VerificationStatus.FALSE,\
                              VerificationStatus.UNK,\
                              VerificationStatus.UNC]:
            return status.upper()

        Logger.error("Invalid Verification Status \"%s\""%status)

    @staticmethod
    def compare(expected, status):
        if (expected == VerificationStatus.UNK) and (status == VerificationStatus.TRUE):
            return True
        return expected == status

class VerificationType(object):
    SAFETY = SAFETY
    LIVENESS = LIVENESS
    EVENTUALLY = EVENTUALLY
    EQUIVALENCE = EQUIVALENCE
    DETERMINISTIC = DETERMINISTIC
    SIMULATION = SIMULATION
    LTL = LTL
    PARAMETRIC = PARAMETRIC


class ProblemsConfig:
    def __init__(self, relative_path:Path, general_config:Dict[str, Any], defaults:Dict[str, Any]):
        self._relative_path = relative_path
        self._general_config = namedtuple('general_config', general_config.keys())(**general_config)
        self._defaults = defaults
        self._problems = []
        self._problems_status = dict()
        self._problem_type = None
        self._hts = None
        self._hts2 = None

    def add_problem(self, problem:NamedTuple):
        self._problems.append(problem)
        self._problems_status[problem] = VerificationStatus.UNC

    def new_problem(self, **kwargs)->None:
        problem_type = self.get_problem_type()
        unknown_kwargs = kwargs.keys() - problem_type._fields
        if unknown_kwargs:
            raise RuntimeError("Expecting only known problem "
                               "options but got {}".format(unknown_kwargs))

        problem_options = self._defaults
        for option, value in kwargs.items():
            problem_options[option] = value

        self._problems.append(problem_type(**problem_options))

    def set_problem_status(self, problem:NamedTuple, status:VerificationStatus):
        assert self._problems_status[problem] == VerificationStatus.UNC, \
            "Not expecting to reset problem status"
        self._problems_status[problem] = status

    @property
    def problems(self)->List[NamedTuple]:
        return self._problems

    def get_problem_status(self, problem:NamedTuple)->VerificationStatus:
        return self._problems_status[problem]

    @property
    def general_config(self)->NamedTuple:
        return self._general_config

    @property
    def hts(self):
        return self._hts

    @hts.setter
    def hts(self, hts:HTS):
        self._hts = hts

    @property
    def hts2(self):
        return self.hts2

    @hts2.setter
    def hts2(self, hts:HTS):
        self._hts2 = hts

    @property
    def relative_path(self):
        return self._relative_path

    def get_problem_type(self, problem_options:Set[str]):
        if self._problem_type is None:
            self._problem_type = namedtuple('Problem', problem_options)
            return self._problem_type
        else:
            assert self(self._problem_type._fields) == problem_options, \
                "Expecting problem type to be static"
            return self._problem_type

class Problems(object):
    abstract_clock = False
    add_clock = False
    assume_if_true = False
    assumptions = None
    bmc_length = 10
    bmc_length_min = 0
    boolean = None
    clock_behaviors = None
    description = None
    default_initial_value = None
    equivalence = None
    expected = None
    formula = None
    full_trace = False
    generators = None
    incremental = None
    lemmas = None
    model_file = None
    name = None
    precondition = None
    problems = None
    prove = False
    relative_path = None
    run_coreir_passes = True
    skip_solving = False
    smt2_tracing = None
    solver_name = None
    solver_options = None
    strategy = None
    symbolic_init = False
    time = False
    trace_all_vars = False
    trace_prefix = None
    trace_vars_change = False
    trace_values_base = None
    traces = None
    vcd = False
    verbosity = None
    verification = None
    zero_init = None
    model_extension = None
    opt_circuit = False
    no_arrays = False
    cardinality = -1
    region = None
    coi = False
    cache_files = False

    _hts = None
    _hts2 = None

    def __init__(self):
        self.problems = []
        # need to create TS for each symbolic init value
        self.symbolic_inits = set()

    def add_problem(self, problem):
        self.problems.append(problem)
        self.symbolic_inits.add(problem.symbolic_init)

    def split_problems(self):
        problems_dic = {}

        for problem in self.problems:
            if problem.attributes() not in problems_dic:
                problems_dic[problem.attributes()] = []

            problems_dic[problem.attributes()].append(problem)

        ret = []
        for key,el in problems_dic.items():
            ret.append(el)

        return ret

    def get_hts(self):
        return self._hts

    def new_problem(self):
        problem = Problem()

        problem.abstract_clock = self.abstract_clock
        problem.add_clock = self.add_clock
        problem.assume_if_true = self.assume_if_true
        problem.assumptions = self.assumptions
        problem.bmc_length = self.bmc_length
        problem.bmc_length_min = self.bmc_length_min
        problem.boolean = self.boolean
        problem.clock_behaviors = self.clock_behaviors
        problem.description = self.description
        problem.default_initial_value = self.default_initial_value
        problem.equivalence = self.equivalence
        problem.expected = self.expected
        problem.formula = self.formula
        problem.full_trace = self.full_trace
        problem.generators = self.generators
        problem.incremental = self.incremental
        problem.lemmas = self.lemmas
        problem.model_file = self.model_file
        problem.name = self.name
        problem.opt_circuit = self.opt_circuit
        problem.no_arrays = self.no_arrays
        problem.precondition = self.precondition
        problem.problems = self.problems
        problem.prove = self.prove
        problem.relative_path = self.relative_path
        problem.run_coreir_passes = self.run_coreir_passes
        problem.skip_solving = self.skip_solving
        problem.smt2_tracing = self.smt2_tracing
        problem.solver_name = self.solver_name
        problem.solver_options = self.solver_options
        problem.strategy = self.strategy
        problem.symbolic_init = self.symbolic_init
        problem.time = self.time
        problem.trace_all_vars = self.trace_all_vars
        problem.trace_prefix = self.trace_prefix
        problem.trace_vars_change = self.trace_vars_change
        problem.trace_values_base = self.trace_values_base
        problem.traces = self.traces
        problem.vcd = self.vcd
        problem.verbosity = self.verbosity
        problem.verification = self.verification
        problem.zero_init = self.zero_init
        return problem

    def generate_problem(self, name, pbm_values):
        pbm = Problem()

        if VERIFICATION not in pbm_values:
            Logger.error("Verification type missing in problem \"%s\""%(name))

        for attr,value in pbm_values.items():
            if hasattr(pbm, attr):
                setattr(pbm, attr, auto_convert(value))
            else:
                Logger.error("Attribute \"%s\" not found"%attr)

        return pbm

    def load_problems(self, problems_file):
        config = configparser.ConfigParser()
        config.optionxform=str
        with open(problems_file, "r") as f:
            config.read_string(u""+f.read())

        self.relative_path = ("/".join(problems_file.split("/")[:-1]))

        if self.relative_path !="":
            self.relative_path += "/"

        for value in config:
            problem = dict(config[value])
            if DEFAULT == value:
                continue
            if GENERAL == value:
                for attr,value in problem.items():
                    if hasattr(self, attr):
                        setattr(self, attr, auto_convert(value))
                    else:
                        if not hasattr(Problem(), attr):
                            Logger.error("Attribute \"%s\" not found"%attr)
                continue
            pbm = self.generate_problem(value, problem)
            pbm.name = value
            self.add_problem(pbm)

class Problem(object):
    assumptions = None
    lemmas = None
    precondition = None
    strategy = None
    incremental = None
    symbolic_init = False
    smt2_tracing = None
    model_extension = None
    opt_circuit = False
    no_arrays = False
    cardinality = -1
    region = None
    coi = False
    default_initial_value = None

    full_trace = False
    trace_vars_change = False
    trace_values_base = None
    trace_all_vars = False
    trace_prefix = None

    verbosity = None
    description = None

    status = VerificationStatus.UNC
    verification = None
    formula = None
    prove = False
    expected = None
    bmc_length = 10
    bmc_length_min = 0
    equivalence = None

    model_file = None
    generators = None
    clock_behaviors = None
    relative_path = None
    name = None
    traces = None
    time = False

    vcd = False
    skip_solving = False

    solver_name = None
    solver_options = None

    def __init__(self):
        self.status = VerificationStatus.UNC
        self.description = ""

    def __repr__(self):
        return self.name

    def attributes(self):
        imp = []

        imp.append(self.assumptions)
        imp.append(self.lemmas)
        imp.append(self.precondition)
        imp.append(self.strategy)
        imp.append(self.incremental)
        imp.append(self.symbolic_init)
        imp.append(self.verification)
        imp.append(self.equivalence)
        imp.append(self.default_initial_value)

        imp.append(self.model_file)
        imp.append(self.generators)
        imp.append(self.clock_behaviors)
        imp.append(self.skip_solving)
        imp.append(self.solver_name)
        imp.append(solver_options)

        return tuple(imp)

class Trace(object):
    name = ""
    description = ""
    extension = None
    strtrace = None
    model = None
    length = None
    infinite = False
    human_readable = False
    prop_vars = None

    def __init__(self, strtrace=None, length=None):
        self.strtrace = strtrace
        self.length = length

    def __repr__(self):
        return str(self.strtrace)

    def __str__(self):
        return str(self.strtrace)
