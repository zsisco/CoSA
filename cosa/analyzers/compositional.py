from collections import defaultdict
import itertools
from typing import Dict, List, Set, Tuple

from cosa.analyzers.mcsolver import BMCSolver, TraceSolver
from cosa.analyzers.marco import get_mucs
from cosa.problem import Trace, VerificationStatus
from cosa.utils.formula_mngm import get_free_variables, get_ground_terms
from cosa.utils.logger import Logger

from pysmt.fnode import FNode
# NOTE: Using the substitute from pysmt here
from pysmt.shortcuts import And, EqualsOrIff, Int, INT, LT, Minus, Not, Or, simplify, Solver, Symbol, substitute, TRUE

class CompositionalEngine(BMCSolver):

    def __init__(self, hts, config):
        BMCSolver.__init__(self, hts, config)

    def simple_search(self, properties:List[FNode],
                      bmc_length:int,
                      bmc_length_min:int)->Tuple[str, Trace, int]:
        '''
        Given a list of properties, this method performs a simple search strategy which attempts to prove
        all the properties compositionally.

        This includes both instantiating universally quantified formulae based on the syntax of the properties,
        as well as attempting to determine a suitable total dependency order on properties.
        '''

        solver_name = "compositional"
        solver = self.solver.copy(solver_name)
        self._reset_assertions(solver)

        if bmc_length != 1 or bmc_length_min != 0:
            raise NotImplementedError("Not handling k-induction for k != 1 yet")

        self._init_at_time(self.hts.vars, bmc_length)

        init  = self.hts.single_init()
        trans = self.hts.single_trans()
        invar = self.hts.single_invar()

        if self.config.simplify:
            init  = simplify(init)
            trans = simplify(trans)
            invar = simplify(invar)

        init_0 = self.at_time(And(init, invar), 0)
        Logger.log("Add init and invar", 2)
        self._add_assertion(solver, init_0)

        failed_base = False
        for p in properties:
            nprop0 = Not(self.at_time(p, 0))
            self._push(solver)
            self._add_assertion(solver, nprop0)
            if self._solve(solver):
                Logger.msg("Property violated in initial state", 0)
                failed_base = True
                model = self._get_model(solver)
                model = self._remap_model(self.hts.vars, model, 0)
                trace = self.generate_trace(model, 0, get_free_variables(p))
                return (VerificationStatus.FALSE, trace, 0)
            self._pop(solver)

        assert not failed_base

        Logger.msg("No properties violated in initial state", 1)

        universal_formulae = self.get_universal_formulae(properties)

        solver_ind = self.solver.copy("compositional-s_ind")
        self._reset_assertions(solver_ind)

        unproven, _ = self.inductive_step(universal_formulae, properties, solver_ind)
        if unproven:
            # do a second pass using all the proven properties
            Logger.msg(" - retrying failed properties - ", 0, not(Logger.level(1)))
            Logger.msg("Trying a second pass on unproven properties", 1)
            unproven, traces = self.inductive_step(universal_formulae, unproven, solver_ind, return_traces=True)

        if unproven:
            return (VerificationStatus.UNK, traces, bmc_length)
        else:
            return (VerificationStatus.TRUE, None, bmc_length)
        # if unproven:
        #     if self.dependency_search(solver_ind, universal_formulae, properties, unproven):
        #         return (VerificationStatus.TRUE, None, bmc_length)
        #     else:
        #         # TODO: Return traces here
        #         return (VerificationStatus.UNK, None, 1)
        # else:
        #     return (VerificationStatus.TRUE, None, bmc_length)

    def inductive_step(self, universal_formulae:Dict[FNode, Tuple[FNode]],
                       properties:List[FNode], solver_ind:TraceSolver,
                       return_traces=False) -> List[FNode]:
        '''
        Check the inductive step compositionally
        Assumes that _init_at_time has already been called
        (i.e. unrolled symbols already created)
        '''

        if return_traces:
            traces = []
        else:
            traces = None

        trans = self.hts.single_trans()
        invar = self.hts.single_invar()
        invar0 = self.at_time(invar, 0)
        self._add_assertion(solver_ind, invar0)
        trans1 = self.unroll(trans, invar, 1)
        self._add_assertion(solver_ind, trans1)

        # can assume all properties in the pre-state
        for prop in properties:
            timed_prop = self.at_time(prop, 0)
            Logger.msg("assuming: " + timed_prop.serialize(100), 2)
            self._add_assertion(solver_ind, timed_prop)

        unproven = list()
        proven = set()
        for num, p in enumerate(properties):
            Logger.msg("Solving property {}: {}".format(num, p.serialize(100)), 1)
            self._push(solver_ind)

            # TODO: Add instantiations in post-state for proven properties
            # add heuristic instantiations
            instantiations = self.heuristic_instantiation(universal_formulae, p)
            for univ_prop, insts in instantiations.items():
                for i in insts:
                    timed_inst = self.at_time(i, 0)
                    Logger.msg('assuming instantiation: ' + timed_inst.serialize(100), 2)
                    self._add_assertion(solver_ind, timed_inst)

                if univ_prop in proven:
                    timed_inst = self.at_time(i, 1)
                    Logger.msg('assuming instantiation: ' + timed_inst.serialize(100), 2)
                    self._add_assertion(solver_ind, timed_inst)

            self._add_assertion(solver_ind, self.at_time(Not(p), 1))

            passed = True
            if self._solve(solver_ind):
                Logger.msg("f", 0, not(Logger.level(1)))
                Logger.msg("Property violated in inductive step", 1)
                unproven.append(p)
                passed = False
                if return_traces:
                    model = self._get_model(solver_ind)
                    model = self._remap_model(self.hts.vars, model, 1)
                    trace = self.generate_trace(model, 1, get_free_variables(p))
                    traces.append(trace)
            else:
                proven.add(p)

            self._pop(solver_ind)

            if passed:
                # property was proven, we can add it to the post-state
                self._add_assertion(solver_ind, self.at_time(p, 1))
                Logger.msg("p", 0, not(Logger.level(1)))
                Logger.msg("assuming property in post-state: " + self.at_time(p, 1).serialize(100), 2)

        return unproven, traces

    # TODO: consider removing this
    def dependency_search(self, solver_ind, universal_formulae:Dict[FNode, Tuple[FNode]],
                          properties:List[FNode], unproven:List[FNode]) -> bool:

        # check to make sure all properties are provable with other properties as assumptions
        unproven_set = set(unproven)
        for prop in unproven:
            self._push(solver_ind)

            for other in unproven_set - {prop}:
                self._add_assertion(solver_ind, self.at_time(other, 1))

            instantiations = self.heuristic_instantiation(universal_formulae, prop)
            for insts in instantiations.values():
                for i in insts:
                    timed_inst = self.at_time(i, 0)
                    Logger.msg('assuming instantiation: ' + timed_inst.serialize(100), 2)
                    self._add_assertion(solver_ind, timed_inst)

            self._add_assertion(solver_ind, self.at_time(Not(prop), 1))
            if self._solve(solver_ind):
                model = self._get_model(solver_ind)
                model = self._remap_model(self.hts.vars, model, 1)
                trace = self.generate_trace(model, 1, get_free_variables(p))
                return (VerificationStatus.FALSE, trace, 1)

            self._pop(solver_ind)

        del unproven_set

        # TODO: don't rely on z3 exclusively -- but MathSAT has a bug
        qf_idl_solver = Solver(name='z3', logic='QF_IDL')

        # add a representative integer for each unproven property
        # will be used to find a dependency order
        dependency_vars = []
        for i, prop in enumerate(unproven):
            dependency_vars.append(Symbol("I%i"%i, INT))

        for i, prop in enumerate(unproven):
            soft_constraints = []
            for p in properties:
                # IMPORTANT : don't assume the property itself in the post state
                if p != prop:
                    # TODO: Support arbitrary k
                    soft_constraints.append(self.at_time(p, 1))
                else:
                    # but we want to keep the indices the same, so add the negated property here
                    soft_constraints.append(Not(self.at_time(p, 1)))

            disjunction_of_dependencies = []
            prop_dep_var = Symbol("I%i"%i, INT)

            for muc in get_mucs(self.config.solver_name, list(hard_constraints), soft_constraints):
                assert muc, "expecting a non-empty unsatisfiable subset"
                dependency_constraint = []
                for idx in muc:
                    # can't precede itself
                    if idx != i:
                        dependency_constraint.append(LT(Minus(prop_dep_var, Symbol("I%i"%idx, INT), Int(0))))
                disjunction_of_dependencies.append(And(dependency_constraint))

            # add the possible dependency orders to the solver
            assert disjunction_of_dependencies, "expecting dependencies to be non-empty"
            assertion = Or(disjunction_of_dependencies)
            qf_idl_solver.add_assertion(assertion)

        # TODO: Enumerate all possible dependency orders and check for one that works
        res = qf_idl_solver.check_sat()
        while res:
            model = self._get_model(solver)

            # TODO: try to prove the properties with this order
            proven = False

            # block this model
            # TODO: need to block the dependency relationship
            block = And([Not(EqualsOrIff(m[0], m[1].constant_value())) for m in model])

            if proven:
                return True

            res = qf_idl_solver.check_sat()

        return False

    def get_universal_formulae(self, properties:List[FNode])->Dict[FNode, Tuple[FNode]]:
        '''
        Returns a dictionary from universally quantified properties to a tuple their free variables
        '''
        # because these are random, properties over these variables are universally quantified
        universal_variables = self.hts.random_vars
        universal_formulae = dict()
        for p in properties:
            overlap = universal_variables.intersection(get_free_variables(p))
            if overlap:
                universal_formulae[p] = tuple(overlap)
        return universal_formulae

    def heuristic_instantiation(self, universal_assumptions:Dict[FNode, Tuple[FNode]],
                                prop:FNode)->List[FNode]:
        '''
        Attempts to instantiate universally quantified formulae, guided by
          the syntax of the provided property (which we are currently trying to prove)

        This is heuristic and entirely syntactic.

        It also checks that prop is not the formula being instantiated.

        INPUTS:
           universal_assumptions: a dictionary from universally quantified formulae to their universal variables
           prop: the property which we want to instantiate formulas for
        '''

        # TODO: Figure out how this works if there are other free variables in the formula
        #       i.e. ones that aren't universally quantified

        # TODO: Figure out how to deal with two properties with the same bound variable
        #       e.g. we're using a skolemized "Random" var to represent a bound universally quantified variable
        #       there's nothing stopping the user from re-using it
        #       the right thing to do is probably just to throw an error -- easier than replacing them ourselves

        instantiated_formulae = defaultdict(list)

        for formula, univ_vars in universal_assumptions.items():
            if formula == prop:
                continue

            types2idx = defaultdict(set)
            for i, s in enumerate(univ_vars):
                assert s.is_symbol()
                types2idx[s.symbol_type()].add(i)

            matching_symbols = [None]*len(univ_vars)
            for t, idxs in types2idx.items():
                matches = tuple(s for s in get_ground_terms(prop) if s.get_type() == t)
                for i in idxs:
                    matching_symbols[i] = matches

            for instvars in itertools.product(*matching_symbols):
                d = {
                    i:u for i, u in zip(univ_vars, instvars)
                }
                instantiated_formulae[formula].append(substitute(formula, d))

        return instantiated_formulae
