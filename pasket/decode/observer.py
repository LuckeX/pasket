import copy as cp
from functools import partial
import re
import logging

import lib.visit as v
import lib.const as C

from .. import util
from ..meta import methods, classes, class_lookup
from ..meta.template import Template
from ..meta.clazz import Clazz
from ..meta.method import Method, find_formals
from ..meta.field import Field
from ..meta.statement import Statement, to_statements
from ..meta.expression import Expression, to_expression, gen_E_bop

class Observer(object):

  ## field comparison
  ## e.g., handleCode_Aux...,ExprBinary,((rcv._date) == (evt._date))
  regex_cmp = r"^(.+\..+) (<|<=|==|!=|>=|>) (.+\..+)$"

  ## iteration direction
  ## e.g., handleCode_Aux...,ExprBinary,idx - 1
  regex_idx = r"^idx (\+|-) 1$"

  @staticmethod
  def exp_of_interest(msg):
    def matched(regex): return re.match(regex, msg)
    return util.exists(matched, [Observer.regex_cmp, Observer.regex_idx])

  ## receiver instance for all the methods in Aux...
  ## e.g., rcv_AuxObserverActionEvent
  regex_rcv = r"(rcv_{}\S+)".format(C.OBS.AUX)

  @staticmethod
  def repl_rcv(msg):
    m = re.match(Observer.regex_rcv, msg)
    if m: return msg.replace(m.group(0), C.J.THIS)
    else: return msg

  # add a mapping from function name to binary expression
  def add_exp(self, func, msg):
    def is_role(role): return func.startswith(role)
    if not util.exists(is_role, C.obs_roles): return
    msg = Observer.repl_rcv(msg)
    util.mk_or_append(self._exps, func, msg)

  ## hole assignments for roles
  ## glblInit_subject_????,StmtAssign,subject_???? = n
  regex_role = r"(({})_{}[^_]+)_.* = (\d+)$".format('|'.join(C.obs_roles), C.OBS.AUX)

  @staticmethod
  def st_of_interest(msg):
    return re.match(Observer.regex_role, msg)

  # add a mapping from role variable to its value chosen by sketch
  def add_st(self, msg):
    m = re.match(Observer.regex_role, msg)
    v, n = m.group(1), m.group(3)
    self._role[v] = n

  # initializer
  def __init__(self, output_path, obs_conf):
    self._output = output_path
    self._demo = util.pure_base(output_path)
    self._obs_conf = obs_conf

    self._cur_mtd = None
    self._exps = {} # { f : [exp...] }
    self._role = {} # { v : n }

    # class roles
    self._subj = {} # { Aux... : Subject }
    self._obsr = {} # { Aux... : Observer }
    self._evts = {} # { Aux... : Event }

    # method roles
    self._attach = {} # { Aux... : Attach }
    self._detach = {} # { Aux... : Detach }
    self._handle = {} # { Aux... : Handle }
    
    # interpret the synthesis result
    with open(self._output, 'r') as f:
      for line in f:
        line = line.strip()
        try:
          items = line.split(',')
          func, kind, msg = items[0], items[1], ','.join(items[2:])
          if Observer.exp_of_interest(msg): self.add_exp(func, msg)
          if Observer.st_of_interest(msg): self.add_st(msg)
        except IndexError: # not a line generated by custom codegen
          pass # if "Total time" in line: logging.info(line)

  @property
  def demo(self):
    return self._demo

  @property
  def subj(self):
    return self._subj

  @subj.setter
  def subj(self, v):
    self._subj = v

  @property
  def obsr(self):
    return self._obsr

  @obsr.setter
  def obsr(self, v):
    self._obsr = v

  @property
  def evts(self):
    return self._evts

  @evts.setter
  def evts(self, v):
    self._evts = v

  @property
  def attach(self):
    return self._attach

  @attach.setter
  def attach(self, v):
    self._attach = v

  @property
  def detach(self):
    return self._detach

  @detach.setter
  def detach(self, v):
    self._detach = v

  @property
  def handle(self):
    return self._handle

  @handle.setter
  def handle(self, v):
    self._handle = v

  @v.on("node")
  def visit(self, node):
    """
    This is the generic method to initialize the dynamic dispatcher
    """

  # add List<@Observer> into @Subject
  @staticmethod
  def add_obs(subj, obsr):
    typ = u"{}<{}>".format(C.J.LNK, obsr.name)
    name = u'_'.join([C.OBS.obs, obsr.name])
    logging.debug("adding field {}.{} of type {}".format(subj.name, name, typ))
    obs = Field(clazz=subj, typ=typ, name=name)
    subj.add_flds([obs])
    setattr(subj, "obs", obs)
    subj.init_fld(obs)

  # attach code
  @staticmethod
  def def_attach(mtd, subj, obsr):
    args = find_formals(mtd.params, [obsr.name])
    logging.debug("adding attach code into {}".format(subj.name))
    add = u"{}.add({});".format(subj.obs.name, ", ".join(args))
    mtd.body = to_statements(mtd, add)

  # detach code
  @staticmethod
  def def_detach(mtd, subj, obsr):
    args = find_formals(mtd.params, [obsr.name])
    logging.debug("adding detach code into {}".format(subj.name))
    rm = u"{}.remove({});".format(subj.obs.name, ", ".join(args))
    mtd.body = to_statements(mtd, rm)

  # handle code
  @staticmethod
  def revise_handle(mtd, upd, aux, subj, obsr, evt):
    body = '\n'.join(map(str,mtd.body))

    # rcv_Aux... -> this
    body = body.replace("rcv_"+aux.name, C.J.THIS)

    # _obs -> _obs_subj
    body = body.replace(C.OBS.obs, u'_'.join([C.OBS.obs, obsr.name]))

    # Aux...reflect(update_Aux..., o, ...) -> o.update(...)
    reflect = "{0}.reflect(update_{0}, o, ".format(aux.name)
    concrete = "o.{}(".format(upd.name)
    body = body.replace(reflect, concrete)

    # List<Aux...> -> List<@Observer>
    # List<Object> -> List<@Observer>
    body = body.replace(aux.name, obsr.name)
    body = body.replace(C.J.OBJ, obsr.name)

    # formal parameter of event type
    args = find_formals(mtd.params, [evt.name])
    body = body.replace("evt", args[0])

    # adjust # of arguments for @Update
    if len(upd.params) < 2:
      upd_param_typ = upd.param_typs[0]
      # either pass @Subject
      if upd_param_typ == subj.name:
        # o.update(this, event) -> o.update(this)
        body = body.replace(", ({}){}".format(evt.name, args[0]), '')
      else: # or @Event
        # o.update(this, event) -> o.update(event)
        body = body.replace("this, ",'')

    logging.debug("revising handle code at {}".format(mtd.name))
    mtd.body = to_statements(mtd, body)

  @v.when(Template)
  def visit(self, node):
    conf = self._obs_conf

    def find_role(lst, aux_name, role):
      try:
        _id = self._role['_'.join([role, aux_name])]
        return lst[int(_id)]
      except KeyError: return None

    regex_ev = r"{}(\S+)".format(C.OBS.AUX)

    for aux_name in node.obs_auxs:
      aux = class_lookup(aux_name)
      evt = getattr(aux, "evt").name

      if evt in conf:
        hdl_cnt, attach_cnt, detach_cnt = conf[evt]
      else:
        hdl_cnt, attach_cnt, detach_cnt = (1, 1, 1)

      # find and store class roles
      find_cls_role = partial(find_role, classes(), aux_name)
      subj, obsr = map(find_cls_role, [C.OBS.SUBJ, C.OBS.OBSR])
      logging.debug("{}: subject: {}".format(aux.evt.name, subj.name))
      logging.debug("{}: observer: {}".format(aux.evt.name, obsr.name))

      self._subj[aux.name] = subj
      self._obsr[aux.name] = obsr
      self._evts[aux.name] = aux.evt

      # find and store method roles
      find_mtd_role = partial(find_role, methods(), aux_name)

      if attach_cnt == 0: attach = None
      else: # attach_cnt == 1
        attach = find_mtd_role(C.OBS.A)
        logging.debug("attach: {}.{}".format(attach.clazz.name, attach.name))

      if detach_cnt == 0: detach = None
      else: # detach_cnt == 1
        detach = find_mtd_role(C.OBS.D)
        logging.debug("detach: {}.{}".format(detach.clazz.name, detach.name))

      handle, update = map(find_mtd_role, [C.OBS.H, C.OBS.U])
      logging.debug("handle: {}.{}".format(handle.clazz.name, handle.name))
      logging.debug("update: {}.{}".format(update.clazz.name, update.name))

      if attach: self._attach[aux.name] = attach
      if detach: self._detach[aux.name] = detach
      self._handle[aux.name] = handle

      # concretize @Subject if an interface is chosen
      if subj.is_itf:
        if attach.clazz != detach.clazz:
          logging.error("attach and detach should belong to the same class")
          logging.error("{} != {}".format(attach.clazz.name, detach.clazz.name))
          raise Exception
        else:
          subj = attach.clazz
          logging.debug("{}: subject: {} => {}".format(aux.evt.name, self._subj[aux.name].name, subj.name))
          self._subj[aux.name] = subj

      # add List<@Observer> into @Subject
      Observer.add_obs(subj, obsr)

      # insert or move code snippets from Aux classes to actual participants
      if attach: Observer.def_attach(attach, subj, obsr)
      if detach: Observer.def_detach(detach, subj, obsr)

      handle.body = aux.mtd_handle.body
      Observer.revise_handle(handle, update, aux, subj, obsr, aux.evt)
      setattr(subj, "handle", handle)

      old = "handleCode_{0}_{0}_{0}_{1}".format(aux.name, aux.evt.name)
      concrete = repr(handle)
      self._exps[concrete] = cp.deepcopy(self._exps[old])
      self._exps.pop(old, None)

      # remove Aux class
      node.classes.remove(aux)

  @v.when(Clazz)
  def visit(self, node): pass

  ## class Dispatcher {
  ##   Aux... aux...;
  ## }
  ##   ->
  ## class Dispatcher {
  ##   SUBJ.. subj...;
  ## }
  @v.when(Field)
  def visit(self, node):
    if C.OBS.AUX in node.typ and node.name == node.typ.lower():
      subj = self._subj[node.typ]
      node.typ = subj.name
      node.name = subj.lower()

  # Aux...subjectCall(...);
  regex_one = r"^{}\S+\.subjectCall\(.*\);$".format(C.OBS.AUX)

  @v.when(Method)
  def visit(self, node):
    self._cur_mtd = node
    if not node.body: return
    cls = node.clazz
    # remove auxiliary initializing statements
    if node.is_init:
      def tmp_filter(st): return C.OBS.tmp not in str(st)
      node.body = filter(tmp_filter, node.body)

    else: # node.is_init
      # remove subjectCall() call
      s = unicode(node.body[0])
      m = re.match(Observer.regex_one, s)
      if m:
        logging.debug("at {}, removing {}".format(node.name, s))
        # assume that call is the only statement in the method
        node.body.pop(0)

  @v.when(Statement)
  def visit(self, node):
    if node.kind == C.S.EXP and node.e.kind == C.E.CALL:
      ## Aux...reflect(Aux...handle..., rcv, ...);
      ##   ->
      ## rcv.handle(...);
      call = unicode(node)
      if call.startswith(C.OBS.AUX) and \
          "reflect" in call and C.OBS.H in call:
        aux_name = call.split('.')[0]
        _id = self._role['_'.join([C.OBS.H, aux_name])]
        handle = methods()[int(_id)]

        old = u"{0}.reflect({0}.handle_{0}, rcv, ".format(aux_name)
        new = u"rcv.{}(".format(handle.name)
        concrete = call.replace(old, new)

        # TODO: more precise sig match
        l_param = concrete.find('(')
        r_param = concrete.rfind(')')
        f = concrete[:l_param]
        args = concrete[l_param+1:r_param]
        rm_null = lambda arg: arg.strip().replace(C.J.N, '')
        new_args = filter(None, map(rm_null, args.split(',')))
        new_call = u"{}({});".format(f, ','.join(new_args))
        logging.debug("{} -> {}".format(call, new_call))
        return to_statements(self._cur_mtd, new_call)

    ## Aux... rcv = obj.aux...;
    ##   ->
    ## SUBJ... rcv = obj.aux...;
    elif node.kind == C.S.ASSIGN:
      if hasattr(node.le, "ty") and C.OBS.AUX in node.le.ty:
        node.le.ty = self._subj[node.le.ty].name

    # discard unnecessary statements that were suppose to add dispatchers
    elif node.kind == C.S.IF:
      guard = str(node.e)
      if guard in "false":
        logging.debug("removing true branch in {}".format(self._cur_mtd.name))
        return node.f
      elif guard in "true":
        logging.debug("removing false branch in {}".format(self._cur_mtd.name))
        return node.t

    elif node.kind == C.S.FOR:
      ## for (Observer o : _obs) { ... }
      ##   ->
      ## Iterator iter = _obs.(iterator | descendingIterator)();
      ## while (iter.hasNext()) {
      ##   Observer o = (Observer)iter.next();
      ##   ...
      ## }
      cls = self._cur_mtd.clazz
      if hasattr(cls, "obs") and node.init.id in cls.obs.name:
        for exp in self._exps[repr(self._cur_mtd)]:
          m = re.match(Observer.regex_idx, exp)
          if not m: continue
          reverse = m.group(1) == '-'
          msg = "resolved: iterator for {}: {{}}".format(node.init.id)
          if reverse: logging.debug(msg.format("backward"))
          else: logging.debug(msg.format("forward"))

          direction = "iterator"
          if reverse: direction = "descendingIterator"
          iterator = '_'.join(["iter", node.init.id])
          body = u"""
            Iterator {iterator} = {node.init.id}.{direction}();
            while({iterator}.hasNext()) {{
              {node.i.typ} {node.i.id} = ({node.i.typ}){iterator}.next();
            }}""".format(**locals())
          ss = to_statements(self._cur_mtd, body)
          ss[-1].b.extend(node.b)
          return ss

    return [node]

  ## subtype relation encoding: subcls(n, id)
  regex_sub = r"^subcls\((\d+), (.+)\)$"

  @v.when(Expression)
  def visit(self, node):
    if node.kind == C.E.ANNO:
      _anno = node.anno
      ## @Compare(exps) -> exps[0] ?? exps[1]
      if _anno.name == C.A.CMP:
        exp0 = str(_anno.exps[0])
        exp0_f = exp0.split('.')[-1]
        exp1 = str(_anno.exps[1])
        exp1_f = exp1.split('.')[-1]
        for exp in self._exps[repr(self._cur_mtd)]:
          m = re.match(Observer.regex_cmp, exp)
          if not m: continue
          if exp0_f in m.group(1) and exp1_f in m.group(3):
            resolved = ' '.join([exp0, m.group(2), exp1])
            logging.debug("resolved: " + resolved)
            return gen_E_bop(unicode(m.group(2)), _anno.exps[0], _anno.exps[1])

      ## @CompareString(exps) -> exps[0].equals(exps[1])
      elif _anno.name == C.A.CMP_STR:
        return to_expression(u"{}.equals({})".format(*map(str, _anno.exps)))

    elif node.kind == C.E.ID:
      if "auxobserver" in node.id:
        l = node.id
        aux_name = l[:1].upper() + l[1:3] + l[3:4].upper() + l[4:]
        node.id = self._subj[aux_name].name.lower()

    ## subcls(x, y) -> eval(cls_x <= cls_y)
    elif node.kind == C.E.CALL:
      exp = str(node)
      m = re.match(Observer.regex_sub, exp)
      if m and C.OBS.SUBJ in m.group(2):
        x = m.group(1)
        y = self._role[m.group(2).split('.')[-1]]
        cls_x, cls_y = map(lambda i: Clazz.clss()[int(i)], [x, y])
        return to_expression(u"{}".format(str(cls_x <= cls_y).lower()))

    ## (Aux...) x -> (SUBJ) x
    elif node.kind == C.E.CAST and C.OBS.AUX in node.ty.id:
      node.ty.id = self._subj[node.ty.id].name

    return node

