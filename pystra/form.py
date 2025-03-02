#!/usr/bin/python -tt
# -*- coding: utf-8 -*-

import os
import numpy as np
import math
import scipy.optimize as opt
import scipy.special as spec
from scipy.stats import norm

from .model import *
from .correlation import *
from .distributions import *
from .cholesky import *
from .limitstate import *
from .stepsize import *


class Form(object):
    """First Order Reliability Method (FORM)

    Let :math:`{\\bf Z}` be a set of uncorrelated and standardized normally
    distributed random variables :math:`( Z_1 ,\dots, Z_n )` in the normalized
    z-space, corresponding to any set of random variables :math:`{\\bf X} = (
    X_1 , \dots , X_n )` in the physical x-space, then the limit state surface
    in x-space is also mapped on the corresponding limit state surface in
    z-space.

    The reliability index :math:`\\beta` is the minimum distance from the
    z-origin to the failure surface. This distance :math:`\\beta` can directly
    be mapped to a probability of failure

    .. math::
       :label: eq:2_90

              p_f \\approx p_{f1} = \Phi(-\\beta)

    this corresponds to a linearization of the failure surface. The
    linearization point is the design point :math:`{\\bf z}^*`. This procedure
    is called First Order Reliability Method (FORM) and :math:`\beta` is the
    First Order Reliability Index. [Madsen2006]_

    :Attributes:
      - analysis_option (AnalysisOption): Option for the structural analysis
      - limit_state (LimitState): Information about the limit state
      - stochastic_model (StochasticModel): Information about the model
    """

    def __init__(self, analysis_options=None, limit_state=None, stochastic_model=None):

        # The stochastic model
        if stochastic_model is None:
            self.model = StochasticModel()
        else:
            self.model = stochastic_model

        # Options for the calculation
        if analysis_options is None:
            self.options = AnalysisOptions()
        else:
            self.options = analysis_options

        # The limit state function
        if limit_state is None:
            self.limitstate = LimitState()
        else:
            self.limitstate = limit_state

        self.i = None
        self.u = None
        self.x = None
        self.J = None
        self.G = None
        self.Go = None
        self.gradient = None
        self.alpha = None
        self.gamma = None
        self.d = None
        self.step = None
        self.beta = None
        self.Pf = None

        # Computation of modified correlation matrix R0
        computeModifiedCorrelationMatrix(self)

        # Cholesky decomposition
        computeCholeskyDecomposition(self)

        # Compute starting point for the algorithm
        self.computeStartingPoint()

        # Iterations
        # Set parameters for the iterative loop
        # Initialize counter
        i = 1
        # Convergence is achieved when convergence is set to True
        convergence = False

        # loope
        while not convergence:
            if self.options.printOutput():
                print(".......................................")
                print("Now carrying out iteration number:", i)

            # Compute Transformation from u to x space
            self.computeTransformation()

            # Compute the Jacobian
            self.computeJacobian()

            # Evaluate limit-state function and its gradient
            self.computeLimitState()

            # Set scale parameter Go and inform about struct. resp.
            if i == 1:
                self.Go = self.G
                if self.options.printOutput():
                    print("Value of limit-state function in the first step:", self.G)

            # Compute alpha vector
            self.computeAlpha()

            # Compute gamma vector
            self.computeGamma()

            # Check convergence
            e1 = np.absolute(self.G * self.Go ** (-1))[0]
            e2 = np.linalg.norm(self.u - self.alpha.dot(self.u).dot(self.alpha))
            condition1 = e1 < self.options.getE1()
            condition2 = e2 < self.options.getE2()
            condition3 = i == self.options.getImax()
            if self.options.printOutput():
                print(f"e1 = {e1:1.6e} , e2 = {e2:1.6e}")

            if condition1 and condition2 or condition3:
                self.i = i
                convergence = True

            # space for some recording stuff

            # Take a step if convergence is not achieved
            if not convergence:
                # Determine search direction
                self.computeSearchDirection()

                # Determine step size
                self.computeStepSize()

                # Determine new trial point
                u_new = self.u + self.step * self.d

                # Prepare for a new round in the loop
                self.u = u_new[0]  # np.transpose(u_new)
                i += 1

        # Compute beta value
        self.computeBeta()

        # Compute failure probability
        self.computeFailureProbability()

        # Show Results
        if self.options.printOutput():
            self.showResults()

    def computeStartingPoint(self):
        """Compute starting point for the algorithm"""
        x = np.array([])
        marg = self.model.getMarginalDistributions()
        for i in range(len(marg)):
            x = np.append(x, marg[i].getStartPoint())
        self.u = x_to_u(x, self.model)

    def computeTransformation(self):
        """Compute transformation from u to x space"""
        self.x = np.transpose([u_to_x(self.u, self.model)])

    def computeJacobian(self):
        """Compute the Jacobian"""
        J_u_x = jacobian(self.u, self.x, self.model)
        J_x_u = np.linalg.inv(J_u_x)
        self.J = J_x_u

    def computeLimitState(self):
        """Evaluate limit-state function and its gradient"""
        G, gradient = evaluateLimitState(
            self.x, self.model, self.options, self.limitstate
        )
        self.G = G
        self.gradient = np.dot(np.transpose(gradient), self.J)

    def computeAlpha(self):
        """Compute alpha vector"""
        self.alpha = -self.gradient * np.linalg.norm(self.gradient) ** (-1)

    def computeGamma(self):
        """Compute gamma vector"""
        self.gamma = np.diag(np.diag(np.sqrt(np.dot(self.J, np.transpose(self.J)))))
        # Importance vector gamma
        matmult = np.dot(np.dot(self.alpha, self.J), self.gamma)
        importance_vector_gamma = matmult * np.linalg.norm(matmult) ** (-1)

    def computeSearchDirection(self):
        """Determine search direction"""
        self.d = (
            self.G * np.linalg.norm(self.gradient) ** (-1) + self.alpha.dot(self.u)
        ) * self.alpha - self.u

    def computeStepSize(self):
        """Determine step size"""
        if self.options.getStepSize() == 0:
            self.step = getStepSize(
                self.G,
                self.gradient,
                self.u,
                self.d,
                self.model,
                self.options,
                self.limitstate,
            )
        else:
            self.step = self.options.getStepSize()

    def computeBeta(self):
        """Compute beta value"""
        self.beta = np.dot(self.alpha, self.u)

    def computeFailureProbability(self):
        """Compute probability of failure"""
        self.Pf = norm.cdf(-self.beta)

    def showResults(self):
        """Show results"""
        n_hyphen = 54
        print("")
        print("=" * n_hyphen)
        print("")
        print(" RESULTS FROM RUNNING FORM RELIABILITY ANALYSIS")
        print("")
        print(" Number of iterations:     ", self.i)
        print(" Reliability index beta:   ", self.beta[0])
        print(" Failure probability:      ", self.Pf[0])
        print(
            " Number of calls to the limit-state function:",
            self.model.getCallFunction(),
        )
        print("")
        print("=" * n_hyphen)
        print("")

    def showDetailedOutput(self):
        """Get detailed output to console"""
        names = self.model.getVariables().keys()
        consts = self.model.getConstants()
        u_star = self.getDesignPoint()
        x_star = self.getDesignPoint(uspace=False)
        alpha = self.getAlpha()

        n_hyphen = 54
        print("")
        print("=" * n_hyphen)
        print("FORM")
        print("=" * n_hyphen)
        print("{:15s} \t {:1.10e}".format("Pf", self.Pf[0]))
        print("{:15s} \t {:2.10f}".format("BetaHL", self.beta[0]))
        print(
            "{:15s} \t {:d}".format("Model Evaluations", self.model.getCallFunction())
        )
        print("-" * n_hyphen)
        print(
            "{:10s} \t {:>9s} \t {:>12s} \t {:>9s}".format(
                "Variable", "U_star", "X_star", "alpha"
            )
        )
        for i, name in enumerate(names):
            print(
                "{:10s} \t {: 5.6f} \t {:12.6f} \t {:+5.6f}".format(
                    name, u_star[i], x_star[i], alpha[i]
                )
            )
        for name, val in consts.items():
            print(f"{name:10s} \t {'---':>9s} \t {val:12.6f} \t {'---':>9s}")
        print("=" * n_hyphen)
        print("")

    def getBeta(self):
        """Returns the beta value

        :Returns:
          - beta (float): Returns the beta value
        """
        return self.beta[0]

    def getFailure(self):
        """Returns the probability of failure

        :Returns:
          - Pf (float): Returns the probability of failure
        """
        return self.Pf

    def getDesignPoint(self, uspace=True):
        """Returns the design point, defaults to u-space

        :Returns:
          - u (float): Returns the design point in u- or x-space
        """
        if uspace:
            return self.u
        else:
            return u_to_x(self.u, self.model)

    def getAlpha(self, as_dict=False):
        """Returns the alpha vector

        :Returns:
          - alpha (np.array): Returns the alpha vector
        """
        if as_dict:
            names = self.model.getNames()
            alphas = self.alpha[0]
            alpha_dict = {name: alpha for alpha, name in zip(alphas, names)}
            return alpha_dict
        return self.alpha[0]
