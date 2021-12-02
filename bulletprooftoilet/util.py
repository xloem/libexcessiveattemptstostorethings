import asyncio, dis, types, warnings

class Queues:
    def __init__(self, *queues):
        self.queues = queues
        self.tasks = {}
    async def get(self):
        for queue in self.queues:
            if queue not in self.tasks:
                task = asyncio.create_task(queue.get())
                self.tasks[queue] = task
        queue_by_task = {task:queue for queue, task in self.tasks.items()}
        done, pending = await asyncio.wait(self.tasks.values(), return_when = asyncio.FIRST_COMPLETED)
        results = {queue_by_task[task]: task.result() for task in done}
        for queue in results:
            del self.tasks[queue]
        return results

def as_async(func):
    if not asyncio.iscoroutinefunction(func):
        async def asyncfunc(*params, **kwparams):
            return func(*params, **kwparams)
        return asyncfunc
    else:
        return func
 

# it's best not to do this for now, to use any other approach instead
# but recursion problems can likely be generalised away if items are marked for transformation,
# before doing the actual transformation.  then can use queues of checking-for-mark and transforming
# the trick might be that marking can produce a result that is not dependent on any other results
# fully completing.  it might be further simplifiable.

class GlobalMutation:
    def __init__(self, **replacements):
        self._replacements = replacements

        self._needs_replacing_memo_results = {}

        self._globals_dict_maps = {}
        self._replacing_memo = {}

    # there are a couple errors here regarding order of recursion expansion
    # and there are a number of solutions.  it is a pleasant puzzle.
    # but maybe a different solution than mutating the library at runtime could be better,
    #  in this day and age where algorithms could be mutating other things too

    def needs_replacing(self, item, interdeps = None):
        if interdeps is None:
            is_root = True
            interdeps = set()
        else:
            is_root = False
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                if item in interdeps:
                    return RecursionError, interdeps
                if item in self._needs_replacing_memo_results:
                    return self._needs_replacing_memo_results[item], interdeps
                interdeps.add(item)
            except TypeError:
                return False, set()
            if type(item) is types.FunctionType:
                flag, interdeps = self.needs_replacing_func(item, interdeps)
            elif type(item) is types.MethodType:
                flag, interdeps = self.needs_replacing_method(item, interdeps)
            elif type(item) is types.ModuleType:
                flag, interdeps = self.needs_replacing_mod(item, interdeps)
            elif type(item) is types.MethodWrapperType:
                assert False
            elif hasattr(item, '__class__'):
                flag, interdeps = self.needs_replacing_obj(item, interdeps)
            else:
                flag, interdeps = False, set()
            if type(flag) is bool:
                self._needs_replacing_memo_results[item] = flag
                #interdeps.remove(item)
                interdeps = set()
            if is_root:
                if type(flag) is not bool:
                    flag = False
                    for item in interdeps:
                        assert self._needs_replacing_memo_results.get(item) in (None, False)
                        self._needs_replacing_memo_results[item] = False
                interdeps.clear()
            #else:
            #    del self._needs_replacing_memo[item]
            return flag, interdeps
    def replace(self, item):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            needs_replacing, item_interdeps = self.needs_replacing(item)
            if needs_replacing != True:
                if needs_replacing != False:
                    raise needs_replacing
                else:
                    return item
            try:
                if item in self._replacing_memo:
                    return self._replacing_memo[item]
                #self._replacing_memo[item] = RecursionError
            except TypeError:
                return item
            if type(item) is types.FunctionType:
                new_item = self.replace_func(item)
            elif type(item) is types.MethodType:
                new_item = self.replace_method(item)
            elif type(item) is types.ModuleType:
                new_item = self.replace_mod(item)
            elif type(item) is types.MethodWrapperType:
                assert False
            elif hasattr(item, '__class__'):
                new_item = self.replace_obj(item)
            else:
                new_item = item
            if new_item is RecursionError:
                raise new_item
            self._replacing_memo[item] = new_item
            return new_item
    # i am in middle of reimplementing 'replacing' function to make use of 'needs_replacing' functions.  left off right after above def replace()
    def needs_replacing_obj(self, object, interdeps):
        needs_replacing = False
        for name, attr in ((name, getattr(object, name)) for name in dir(object) if hasattr(object, name)):
            if type(attr) is types.MethodType or type(attr) is types.FunctionType:
                attr_needs_replacing, attr_interdeps = self.needs_replacing(attr, interdeps)
                interdeps.update(attr_interdeps)
                if attr_needs_replacing is True:
                    needs_replacing = True
                    break
                elif attr_needs_replacing is RecursionError:
                    needs_replacing = attr_needs_replacing
        return needs_replacing, interdeps
    def replace_obj(self, object):
        self._replacing_memo[object] = object
        changed = False
        for name, attr in (
            (name, getattr(object, name))
            for name in dir(object)
            if hasattr(object, name)
        ):
            #if name == '__init__' and 'aemon' in str(object):
            #    import pdb; pdb.set_trace()
            if type(attr) is types.MethodType or type(attr) is types.FunctionType:
                attr_needs_replacing, attr_interdeps = self.needs_replacing(attr)
                if attr_needs_replacing == True:
                    attr = self.replace(attr)
                    setattr(object, name, attr)
                elif attr_needs_replacing != False:
                    raise attr_needs_replacing
        return object
    def needs_replacing_method(self, method, interdeps):
        return self.needs_replacing(method.__func__, interdeps)
    def replace_method(self, method):
        func = method.__func__
        obj = method.__self__
        func_needs_replacing, func_interdeps = self.needs_replacing(func)
        if func_needs_replacing == True:
            func = self.replace(func)
            method = types.MethodType(
                func,
                obj
            )
        elif func_needs_replacing != False:
            raise func_needs_replacing
        return method
    def needs_replacing_func(self, func, interdeps):
        needs_replacing = False
        closure = func.__closure__
        if closure is not None:
            for cell in closure:
                contents = cell.cell_contents
                if type(contents) is types.FunctionType:
                    contents_need_replacing, contents_interdeps = self.needs_replacing(contents, interdeps)
                    interdeps.update(contents_interdeps)
                    if contents_need_replacing is not False:
                        needs_replacing = contents_need_replacing
                        if needs_replacing is True:
                            break
        if needs_replacing is not True:
            for key, item in func.__globals__.items():
                if key in self._replacements:
                    needs_replacing = True
                    break
                elif type(item) is types.FunctionType:
                    item_needs_replacing, item_interdeps = self.needs_replacing(item, interdeps)
                    interdeps.update(item_interdeps)
                    if item_needs_replacing is not False:
                        needs_replacing = item_needs_replacing
                        if needs_replacing is True:
                            break
        return needs_replacing, interdeps
    def replace_func(self, func):

        closure = func.__closure__
        closure_needs_replacing = False
        if closure is not None:
            for cell in closure:
                contents = cell.cell_contents
                if type(contents) is types.FunctionType:
                    contents_needs_replacing, contents_interdeps = self.needs_replacing(contents)
                    if contents_needs_replacing == True:
                        closure_needs_replacing = True
                    elif contents_needs_replacing != False:
                        raise contents_needs_replacing

        globals_needs_replacing = False
        old_globals = func.__globals__
        new_globals = self._globals_dict_maps.setdefault(id(old_globals), {})
        if len(new_globals) == 0:
            for key, item in old_globals.items():
                if key in self._replacements:
                    globals_needs_replacing = True
                elif type(item) is types.FunctionType:
                    item_needs_replacing, item_interdeps = self.needs_replacing(item)
                    if item_needs_replacing == True:
                        globals_needs_replacing = True
                    elif item_needs_replacing != False:
                        raise item_needs_replacing
            if not globals_needs_replacing:
                new_globals = old_globals
            self._globals_dict_maps[id(old_globals)] = new_globals

        # if this makes recursion issue, then simplest solution is to wrap function in one that can change the closure by e.g. generating func on first call.  reason is so that function can be instantiated to be reused, before closure replacement calls are made
        if closure_needs_replacing:
            new_cells = []
            for cell in closure:
                contents = cell.cell_contents
                if type(contents) is types.FunctionType:
                    contents_needs_replacing, contents_interdeps = self.needs_replacing(contents)
                    if contents_needs_replacing == True:
                        contents = self.replace(contents)
                        cell = types.CellType(contents)
                    elif contents_needs_replacing != False:
                        raise contents_needs_replacing
                new_cells.append(cell)
            closure = tuple(new_cells)

        new_func = types.FunctionType(
            func.__code__,
            new_globals,
            func.__name__,
            func.__defaults__,
            closure)
        new_func.__kwdefaults__ = func.__kwdefaults__
        self._replacing_memo[func] = new_func

        if globals_needs_replacing:
            for key, item in old_globals.items():
                if key in self._replacements:
                    item = self._replacements[key]
                elif type(item) is types.FunctionType:
                    item_needs_replacing, item_interdeps = self.needs_replacing(item)
                    if item_needs_replacing == True:
                        item = self.replace(item)
                    elif item_needs_replacing != False:
                        raise item_needs_replacing
                new_globals[key] = item
            assert new_func.__globals__ is new_globals

        return new_func
    def needs_replacing_mod(self, mod, interdeps):
        needs_replacing = False
        for name in dir(mod):
            if name in self._replacements:
                needs_replacing = True
                break
            else:
                item = getattr(mod, name)
                if name[0] == '_':
                    continue
                elif type(item) is types.ModuleType and item.__package__ != mod.__package__:
                    continue
                else:
                    item_needs_replacing, item_interdeps = self.needs_replacing(item, interdeps)
                    interdeps.update(item_interdeps)
                    if item_needs_replacing is not False:
                        needs_replacing = item_needs_replacing
                        if needs_replacing is True:
                            break
        return needs_replacing, interdeps
    def replace_mod(self, mod):
        class replaced:
            pass
        self._replacing_memo[mod] = replaced

        for name in dir(mod):
            item = self._replacements.get(name)
            if item is None:
                item = getattr(mod, name)
                if name[0] == '_':
                    pass
                elif type(item) is types.ModuleType and item.__package__ != mod.__package__:
                    pass
                else:
                    item = self.replace(item)
            setattr(replaced, name, item)
        return replaced

def replace_all_global_members_with_self_members(object, globalname):
    for name in dir(object):
        attr = getattr(object, name)
        if type(attr) is types.MethodType:
            func = attr.__func__
            replaced = replace_global_member_with_self_member(func, globalname)
            if replaced is not func:
                method = types.MethodType(
                    replaced,
                    object
                )
                setattr(object, name, method)


def replace_global_member_with_self_member(func, globalname, local=True):
    changed = False

    closure = func.__closure__
    if closure is not None:
        new_cells = []
        for cell in closure:
            contents = cell.cell_contents
            if type(contents) is types.FunctionType:
                replaced = replace_global_member_with_self_member(contents, globalname)
                if replaced is not contents:
                    changed = True
                    cell = types.CellType(replaced)
            new_cells.append(cell)
        if changed:
            closure = tuple(new_cells)

    # make sure 'self' is in co_varnames
    varnames = func.__code__.co_varnames
    if 'self' not in varnames:
        selfidx = len(varnames)
        varnames = tuple((*varnames, 'self'))
    else:
        selfidx = varnames.index('self')

    # mutate global loads to self loads
    old_code = func.__code__.co_code
    old_instrs = [*dis.get_instructions(func)]
    new_code = bytes()
    for idx, instr in enumerate(old_instrs):
        if idx + 1 < len(old_instrs):
            next_offset = old_instrs[idx + 1].offset
        else:
            next_offset = len(func.__code__.co_code)
        if instr.opname == 'LOAD_GLOBAL' and instr.argval == globalname:
            new_code += bytes([dis.opmap['LOAD_FAST'], selfidx])
            changed = True
        else:
            new_code += old_code[instr.offset : next_offset]

    if changed:
        # create a new method, and replace the old
        func = types.FunctionType(
            func.__code__.replace(co_varnames = varnames, co_code = new_code),
            func.__globals__,
            func.__name__,
            func.__defaults__,
            closure,
        )
    return func

async def chainparamscpp2checkpoints(filename, **blockchains):
    import bitcoinx, json
    with open(filename) as chainparamsfile:
        content = chainparamsfile.read()
    chunks = content.split('class')
    result = {}
    for chunk in chunks:
        if 'strNetworkID' not in chunk:
            continue
        networkID = chunk.split('strNetworkID', 1)[1].split('=', 1)[1].split(';', 1)[0]
        networkID = json.loads(networkID)
        blockchain = blockchains.get(networkID)
        data = chunk.split('checkpointData', 1)[1].split('{',2)[-1].split(')},\n')
        chkpts = []
        for item in data:
            if ';' in data:
                break
            height, hash = item.split('{',1)[1].split('}',1)[0].split(',')
            hash = hash.split('(',1)[1]
            height = int(height)
            hash = ''.join([chr for chr in hash if chr.isalnum()])
            if blockchain is not None:
                try:
                    header = await blockchain.header(height)
                except Exception as e:
                    print(e)
                    break
                if hash != header.hash:
                    print(height, hash, '!=', header.hash)
                    break
                chkpts.append((height, hash, bitcoinx.bits_to_target(header.bits)))
            else:
                chkpts.append((height, hash))
        result[networkID] = chkpts
    return result
