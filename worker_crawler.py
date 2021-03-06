#coding:utf-8
#!/usr/bin/evn python
# modified 20160529
# use multiprocess to run scrawler and damon parallel
# 

import requests
from requests.exceptions import ConnectionError
import gevent
from gevent.pool import Pool
from gevent import monkey

from multiprocessing import Process, Queue
from redis_inc import RedisQueueConnection
import cPickle
from time import time, sleep
import re, md5

from worker_daemon import Daemon
from worker_daemon import getip

#from pybloomfilter import BloomFilter
from Error import Error

monkey.patch_all(thread=False)

class Crawler:

    def __init__(self, done_que):

        self.showpercounts = 10
        self.timeout = 5
        self.starttime = time()

        self.quit = False

        self.run_que = RedisQueueConnection('running').conn
        self.done_que = done_que
        self.tasks = []
        self.done = 1

        self.errdone = set()
        self.err = Error()
        self.https_enable = 0 

        self.httpget = self.httpget_requests # down method self.httpget_requests | httpget_curl

        self.poolsize = 20
        self.down_pool = Pool(size=self.poolsize)

        self.totalnettime = 0
        self.totaldownsize = 0
        
        self.ip = getip()

    #callback function when greenlet of httpget run done
    def cb_httpget(self, data = None):

        if not data:
            return
        seed, err, headers, content = data

        if err:
            self.handle_error(err,seed)
            return

        data={'seed':seed,'headers':headers,'content':content}
        
        dat = cPickle.dumps(data)
        self.done_que.put_nowait(dat)

        #print "done", seed
        if self.done % self.showpercounts == 0:
            self.out(seed)


    def out(self, seed):

        spendtime = time() - self.starttime
        spendtime = 1 if spendtime == 0 else spendtime
        nowh = str(int(spendtime)/3600)+":" if spendtime>3600 else ""
        now = "%s%02d:%02d" % (nowh, spendtime%3600/60, spendtime%60 )
        print "\n%s\t%s D:%-4d R:%-7d [QPS: %.2f  %.2f]  %s" % (self.ip, now, (self.done), self.run_que.qsize(), \
            self.done/spendtime, self.done/self.totalnettime , str(self.err) )
    
    
    def run(self):

        while self.quit == False:
            try:
                if self.run_que.qsize() == 0:
                    print "run que empty"
                    sleep(10)
                    continue
                url = self.run_que.get()
                #self.down_pool.apply_cb(self.httpget, (url,), callback=self.cb_httpget)
                # spawn is more fast?
                self.down_pool.spawn(self.httpget, url)
                self.done += 1
            except KeyboardInterrupt:
                print "Crawler recv quit singal"
                self.quit = True

        self.down_pool.join()
        print "Crawler over, quit"

    def handle_error(self,e,url):
       
        self.err.lasterrurl = url 
        # do not record the err url, but record the least err url to show
        if e.find('DNSError') > 0 :
            self.err.dns += 1
            #self.err.rdns.append(url)
        elif e.find('reset') > 0 :#Connection reset
            self.err.reset += 1
            #self.err.rreset.append(url)
        elif e.find('Max retries') > 0 or e.find('Connection aborted'): #
            self.err.conntimeout += 1
            #self.err.rconntimeout.append(url)
        elif e.find('refused') > 0: #Connection refused
            self.err.refuse += 1
            #self.err.rrefuse.append(url)

        else:
            self.err.others +=1
            #self.err.rothers.append(url)
            print "Error", url, e

    
    # requests is better than curl in tests
    def httpget_requests(self, url):
       
        #return data
        data = None 
        st = time()
        con = ""
        e = ""
        res_headers = ""
        headers = {
                    'Accept-Language':'zh-CN,zh;q=0.8,zh-TW;q=0.6',
                    'Accept-Encoding':'gzip,deflate',
                    'Connection':'close',
                    'User-Agent':'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36'
                }


        res = None
        done = False
        try:
            with gevent.Timeout(6, False) as timeout:
                #req.max_redirects = 2
                res = requests.get(url, headers = headers )
                con = res.content
                res.close()
                done = True
        except KeyboardInterrupt:
                raise
        except Exception as e:
            e = str(e)
            if res:
                res.close()

            #as for spawn, no callback , we should call by ourself
            data = (url, e, None, None)
            #return url,e,None,None

        et = time()
        self.totalnettime += (et-st)
        #spawn
        if done:
            data = (url, e, res.headers, con)
            
        self.cb_httpget(data)
        #return url, e, res.headers, con

    
def main():
    
    #queue for crawler to put the downloaded sites and daemon to extract urls
    done_que = Queue() 
    worker_daemon = Daemon(done_que)    
    worker_crawler = Crawler(done_que)

    try:
        pd = Process(target=worker_daemon.run)
        pc = Process(target=worker_crawler.run)
        pd.start()
        pc.start() 
        
        pd.join()
        pc.join()
    except KeyboardInterrupt:
        print "Ctrl+C"
        worker_crawler.quit = True



if __name__ == '__main__':

    main()
    
