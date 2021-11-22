import dis, types

class GlobalMutation:
    def __init__(self, **replacements):
        self._globals_dict_maps = {}
        self._replacements = replacements
        self._memo = set()
    def replace(self, item):
        if item in self._memo:
            return item, False
        self._memo.add(item)
        if type(item) is types.FunctionType:
            new_item, changed = self.replace_func(item)
        elif type(item) is types.MethodType:
            new_item, changed = self.replace_method(item)
        elif type(item) is types.MethodWrapperType:
            assert False
        elif hasattr(item, '__class__'):
            new_item, changed = self.replace_obj(item)
        else:
            new_item, changed = item, False
        #self._replaced.add(new_item)
        self._memo.remove(item)
        return new_item, changed
    def replace_obj(self, object):
        changed = False
        for name in dir(object):
            attr = getattr(object, name)
            if type(attr) is types.MethodType or type(attr) is types.FunctionType:
                attr, attr_changed = self.replace(attr)
                if attr_changed:
                    setattr(object, name, attr)
                    changed = True
        return object, changed
    def replace_method(self, method):
        func = method.__func__
        obj = method.__self__
        func, func_changed = self.replace(func)
        if func_changed:
            method = types.MethodType(
                func,
                obj
            )
        return method, func_changed
    def replace_func(self, func):
        changed = False
        closure = func.__closure__
        if closure is not None:
            new_cells = []
            for idx, cell in enumerate(closure):
                contents = cell.cell_contents
                if type(contents) is types.FunctionType:
                    contents, contents_changed = self.replace(contents)
                    if contents_changed:
                        changed = True
                        cell = types.CellType(contents)
                new_cells.append(cell)
            if changed:
                closure = tuple(new_cells)
        old_globals = func.__globals__
        new_globals = self._globals_dict_maps.get(id(old_globals))
        if new_globals is None:
            new_globals = {}
            for key, item in old_globals.items():
                if key in self._replacements:
                    changed = True
                    item = self._replacements[key]
                elif type(item) is types.FunctionType:
                    item, item_changed = self.replace(item)
                    changed = changed or item_changed
                new_globals[key] = item
            if not changed:
                new_globals = old_globals
            self._globals_dict_maps[id(old_globals)] = new_globals
        elif new_globals is not old_globals:
            changed = True
        if changed:
            new_func = types.FunctionType(
                func.__code__,
                new_globals,
                func.__name__,
                func.__defaults__,
                closure,
            )
            new_func.__kwdefaults__ = func.__kwdefaults__
            return new_func, True
        else:
            return func, False
            

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
        for idx, cell in enumerate(closure):
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
